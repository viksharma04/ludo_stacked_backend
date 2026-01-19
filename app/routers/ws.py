import json
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.schemas.ws import (
    ErrorPayload,
    MessageType,
    RoomSnapshot,
    SeatSnapshot,
    WSClientMessage,
    WSCloseCode,
    WSServerMessage,
)
from app.services.room.service import RoomSnapshotData, get_room_service
from app.services.websocket.auth import get_ws_authenticator
from app.services.websocket.handlers import HandlerContext, dispatch
from app.services.websocket.manager import get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Rate limiting configuration
MAX_MESSAGE_SIZE = 64 * 1024  # 64 KB
MAX_MESSAGES_PER_SECOND = 10
RATE_LIMIT_WINDOW = 1.0  # seconds


def _to_room_snapshot(data: RoomSnapshotData) -> RoomSnapshot:
    """Convert RoomSnapshotData to RoomSnapshot schema."""
    return RoomSnapshot(
        room_id=data.room_id,
        code=data.code,
        status=data.status,
        visibility=data.visibility,
        ruleset_id=data.ruleset_id,
        max_players=data.max_players,
        seats=[
            SeatSnapshot(
                seat_index=s.seat_index,
                user_id=s.user_id,
                display_name=s.display_name,
                ready=s.ready,
                connected=s.connected,
                is_host=s.is_host,
            )
            for s in data.seats
        ],
        version=data.version,
    )


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
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token"),
    room_code: str = Query(..., min_length=6, max_length=6, description="Room code to connect to"),
):
    """WebSocket endpoint for real-time room connections.

    Clients connect with: ws://host/api/v1/ws?token=<jwt>&room_code=ABC123

    Authentication and room access are validated before the connection is accepted.
    User must have a seat in the room to connect.
    On successful connection, server sends a 'connected' message with room snapshot.
    """
    # Validate token BEFORE accepting connection (async to avoid blocking)
    authenticator = get_ws_authenticator()
    auth_result = await authenticator.validate_token(token)

    if not auth_result.success:
        logger.warning("WS connection rejected: %s", auth_result.error)
        close_code = WSCloseCode.AUTH_EXPIRED if auth_result.expired else WSCloseCode.AUTH_FAILED
        await websocket.close(code=close_code)
        return

    user_id = auth_result.payload.get("sub") if auth_result.payload else None
    if not user_id:
        logger.warning("WS connection rejected: missing user_id in token")
        await websocket.close(code=WSCloseCode.AUTH_FAILED)
        return

    # Validate room access (async to avoid blocking)
    room_service = get_room_service()
    room_id, error = await room_service.validate_room_access(user_id, room_code)
    if error:
        logger.warning(
            "WS connection rejected for user %s: %s (room_code=%s)",
            user_id,
            error,
            room_code,
        )
        close_code = (
            WSCloseCode.ROOM_NOT_FOUND
            if error == "ROOM_NOT_FOUND"
            else WSCloseCode.ROOM_ACCESS_DENIED
        )
        await websocket.close(code=close_code)
        return

    # Update seat connected status and get fresh snapshot
    await room_service.update_seat_connected_by_user(room_id, user_id, connected=True)
    room_snapshot_data = await room_service.get_room_snapshot(room_id)
    if not room_snapshot_data:
        logger.error("Room %s not found in Redis after access validation", room_id)
        await websocket.close(code=WSCloseCode.ROOM_NOT_FOUND)
        return

    room_snapshot = _to_room_snapshot(room_snapshot_data)

    # Accept the connection
    await websocket.accept()
    logger.info("WS connection accepted for user %s in room %s", user_id, room_code)

    # Register with connection manager (sends "connected" message to user)
    manager = get_connection_manager()
    connection = await manager.connect(websocket, user_id, room_id, room_snapshot)

    # Broadcast room_updated to other room members
    await manager.send_to_room(
        room_id,
        WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            payload=room_snapshot.model_dump(),
        ),
        exclude_connection=connection.connection_id,
    )

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
            ctx = HandlerContext(
                connection_id=connection.connection_id,
                user_id=user_id,
                message=message,
                manager=manager,
            )

            result = await dispatch(ctx)

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
        # Clean up rate limiter for this connection
        _rate_limiter.remove(connection.connection_id)

        # Disconnect from manager (handles seat connected update and ready reset)
        await manager.disconnect(connection.connection_id)

        # Broadcast updated room state to remaining members
        updated_snapshot_data = await room_service.get_room_snapshot(room_id)
        if updated_snapshot_data:
            await manager.send_to_room(
                room_id,
                WSServerMessage(
                    type=MessageType.ROOM_UPDATED,
                    payload=_to_room_snapshot(updated_snapshot_data).model_dump(),
                ),
            )
