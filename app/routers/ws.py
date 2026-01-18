import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.schemas.ws import (
    MessageType,
    PongPayload,
    WSClientMessage,
    WSCloseCode,
    WSServerMessage,
)
from app.services.websocket.auth import WSAuthenticator
from app.services.websocket.manager import get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token"),
):
    """WebSocket endpoint for real-time connections.

    Clients connect with: ws://host/api/v1/ws?token=<jwt>

    Authentication is validated before the connection is accepted.
    On successful connection, server sends a 'connected' message with connection details.
    """
    # Validate token BEFORE accepting connection
    authenticator = WSAuthenticator()
    auth_result = authenticator.validate_token(token)

    if not auth_result.success:
        logger.warning("WS connection rejected: %s", auth_result.error)
        close_code = WSCloseCode.AUTH_EXPIRED if auth_result.expired else WSCloseCode.AUTH_FAILED
        await websocket.close(code=close_code)
        return

    user_id = auth_result.payload.get("sub")
    if not user_id:
        logger.warning("WS connection rejected: missing user_id in token")
        await websocket.close(code=WSCloseCode.AUTH_FAILED)
        return

    # Accept the connection
    await websocket.accept()
    logger.info("WS connection accepted for user %s", user_id)

    # Register with connection manager
    manager = get_connection_manager()
    connection = await manager.connect(websocket, user_id)

    try:
        while True:
            # Check if connection is still open
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.debug("WebSocket no longer connected, exiting loop")
                break

            # Receive message
            data = await websocket.receive_json()

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
                        error="Invalid message format",
                        code=WSCloseCode.INVALID_DATA,
                    ),
                )
                continue

            # Handle message types
            if message.type == MessageType.PING:
                # Update heartbeat and respond with pong
                await manager.heartbeat(connection.connection_id)
                await manager.send_to_connection(
                    connection.connection_id,
                    WSServerMessage(
                        type=MessageType.PONG,
                        request_id=message.request_id,
                        payload=PongPayload().model_dump(),
                    ),
                )
                logger.debug(
                    "Ping/pong for connection %s",
                    connection.connection_id,
                )
            else:
                logger.debug(
                    "Unhandled message type %s from connection %s",
                    message.type,
                    connection.connection_id,
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
        await manager.disconnect(connection.connection_id)
