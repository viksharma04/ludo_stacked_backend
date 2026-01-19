import logging

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
from app.services.websocket.auth import WSAuthenticator
from app.services.websocket.handlers import HandlerContext, dispatch
from app.services.websocket.manager import get_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


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
    # Validate token BEFORE accepting connection
    authenticator = WSAuthenticator()
    auth_result = authenticator.validate_token(token)

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

    # Validate room access
    room_service = get_room_service()
    room_id, error = room_service.validate_room_access(user_id, room_code)
    if error:
        logger.warning(
            "WS connection rejected for user %s: %s (room_code=%s)",
            user_id,
            error,
            room_code,
        )
        close_code = (
            WSCloseCode.ROOM_NOT_FOUND if error == "ROOM_NOT_FOUND" else WSCloseCode.ROOM_ACCESS_DENIED
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
        # Disconnect and update seat connected status
        await manager.disconnect(connection.connection_id)

        # Update seat connected=false and broadcast to remaining room members
        await room_service.update_seat_connected_by_user(room_id, user_id, connected=False)
        updated_snapshot_data = await room_service.get_room_snapshot(room_id)
        if updated_snapshot_data:
            await manager.send_to_room(
                room_id,
                WSServerMessage(
                    type=MessageType.ROOM_UPDATED,
                    payload=_to_room_snapshot(updated_snapshot_data).model_dump(),
                ),
            )
