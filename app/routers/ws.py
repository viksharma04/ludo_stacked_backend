import asyncio
import json
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.schemas.ws import (
    ErrorPayload,
    MessageType,
    WSClientMessage,
    WSCloseCode,
    WSServerMessage,
)
from app.services.websocket.handlers import HandlerContext, dispatch
from app.services.websocket.manager import get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Rate limiting configuration
MAX_MESSAGE_SIZE = 64 * 1024  # 64 KB
MAX_MESSAGES_PER_SECOND = 10
RATE_LIMIT_WINDOW = 1.0  # seconds

# Authentication timeout (seconds to send authenticate message after connecting)
AUTH_TIMEOUT = 30.0


class RateLimiter:
    """Simple token bucket rate limiter per connection."""

    def __init__(
        self, max_tokens: int = MAX_MESSAGES_PER_SECOND, window: float = RATE_LIMIT_WINDOW
    ):
        self.max_tokens = max_tokens
        self.window = window
        self._tokens: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, connection_id: str) -> bool:
        """Check if a message is allowed under rate limiting."""
        now = time.time()
        cutoff = now - self.window

        # Remove expired timestamps
        self._tokens[connection_id] = [t for t in self._tokens[connection_id] if t > cutoff]

        # Check if under limit
        if len(self._tokens[connection_id]) >= self.max_tokens:
            return False

        # Record this message
        self._tokens[connection_id].append(now)
        return True

    def remove(self, connection_id: str) -> None:
        """Remove rate limit tracking for a connection."""
        self._tokens.pop(connection_id, None)


# Global rate limiter instance
_rate_limiter = RateLimiter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time room connections.

    Clients connect with: ws://host/api/v1/ws

    After connection is accepted, clients must send an 'authenticate' message
    within 30 seconds containing their JWT token and room_code:

        { "type": "authenticate", "payload": { "token": "...", "room_code": "ABC123" } }

    On successful authentication, server sends an 'authenticated' message with
    the room snapshot. Other messages are rejected until authentication completes.
    """
    # Accept the connection immediately (unauthenticated)
    await websocket.accept()

    # Register unauthenticated connection
    manager = get_connection_manager()
    connection = manager.register_unauthenticated(websocket)
    logger.info("WS connection accepted (unauthenticated): %s", connection.connection_id)

    # Start authentication timeout task
    auth_timeout_task: asyncio.Task | None = None

    async def auth_timeout():
        """Close connection if not authenticated within timeout."""
        await asyncio.sleep(AUTH_TIMEOUT)
        if not connection.authenticated:
            logger.warning(
                "Connection %s timed out waiting for authentication",
                connection.connection_id,
            )
            try:
                await websocket.close(code=WSCloseCode.AUTH_TIMEOUT)
            except Exception:
                pass

    auth_timeout_task = asyncio.create_task(auth_timeout())

    try:
        while True:
            # Check if connection is still open
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.debug("WebSocket no longer connected, exiting loop")
                break

            # Receive raw message with size limit check
            try:
                message_data = await websocket.receive()
            except Exception as e:
                logger.debug("Error receiving message: %s", e)
                break

            # Handle disconnect message
            if message_data.get("type") == "websocket.disconnect":
                break

            # Get raw bytes/text for size check
            raw_text = message_data.get("text")
            raw_bytes = message_data.get("bytes")

            if raw_text:
                message_size = len(raw_text.encode("utf-8"))
            elif raw_bytes:
                message_size = len(raw_bytes)
            else:
                continue

            # Check message size limit
            if message_size > MAX_MESSAGE_SIZE:
                logger.warning(
                    "Message too large from connection %s: %d bytes (max %d)",
                    connection.connection_id,
                    message_size,
                    MAX_MESSAGE_SIZE,
                )
                await manager.send_to_connection(
                    connection.connection_id,
                    WSServerMessage(
                        type=MessageType.ERROR,
                        payload=ErrorPayload(
                            error_code="MESSAGE_TOO_LARGE",
                            message=f"Message exceeds maximum size of {MAX_MESSAGE_SIZE} bytes",
                        ).model_dump(),
                    ),
                )
                continue

            # Check rate limit
            if not _rate_limiter.is_allowed(connection.connection_id):
                logger.warning(
                    "Rate limit exceeded for connection %s",
                    connection.connection_id,
                )
                await manager.send_to_connection(
                    connection.connection_id,
                    WSServerMessage(
                        type=MessageType.ERROR,
                        payload=ErrorPayload(
                            error_code="RATE_LIMITED",
                            message="Too many messages, please slow down",
                        ).model_dump(),
                    ),
                )
                continue

            # Parse JSON from raw text
            if not raw_text:
                continue

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid JSON from connection %s",
                    connection.connection_id,
                )
                await manager.send_to_connection(
                    connection.connection_id,
                    WSServerMessage(
                        type=MessageType.ERROR,
                        payload=ErrorPayload(
                            error_code="INVALID_JSON",
                            message="Invalid JSON format",
                        ).model_dump(),
                    ),
                )
                continue

            # Parse and validate message
            try:
                message = WSClientMessage.model_validate(data)
            except ValidationError as e:
                logger.warning(
                    "Invalid message from connection %s: %s",
                    connection.connection_id,
                    e,
                )
                await manager.send_to_connection(
                    connection.connection_id,
                    WSServerMessage(
                        type=MessageType.ERROR,
                        payload=ErrorPayload(
                            error_code="INVALID_MESSAGE",
                            message="Invalid message format",
                        ).model_dump(),
                    ),
                )
                continue

            # Dispatch message to handler
            # Note: user_id may be None for unauthenticated connections
            # The authenticate handler will set it, other handlers check for auth
            ctx = HandlerContext(
                connection_id=connection.connection_id,
                user_id=connection.user_id or "",
                message=message,
                manager=manager,
            )

            result = await dispatch(ctx)

            # Cancel auth timeout once authenticated
            if connection.authenticated and auth_timeout_task and not auth_timeout_task.done():
                auth_timeout_task.cancel()

            if result is None:
                logger.debug(
                    "Unhandled message type %s from connection %s",
                    message.type,
                    connection.connection_id,
                )
                continue

            # Send response to requester
            if result.response:
                await manager.send_to_connection(
                    connection.connection_id,
                    result.response,
                )

            # Broadcast to room if needed
            if result.broadcast and result.room_id:
                await manager.send_to_room(
                    result.room_id,
                    result.broadcast,
                    exclude_connection=connection.connection_id,
                )

    except WebSocketDisconnect as e:
        logger.info(
            "WS disconnected: connection %s, code %s",
            connection.connection_id,
            e.code,
        )
    except Exception as e:
        logger.error(
            "WS error for connection %s: %s",
            connection.connection_id,
            e,
        )
    finally:
        # Cancel auth timeout if still running
        if auth_timeout_task and not auth_timeout_task.done():
            auth_timeout_task.cancel()

        # Clean up rate limiter for this connection
        _rate_limiter.remove(connection.connection_id)

        # Disconnect from manager (handles seat connected update, ready reset,
        # and broadcasting updated room state to remaining members)
        await manager.disconnect(connection.connection_id)
