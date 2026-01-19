import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.schemas.ws import (
    CreateRoomPayload,
    ErrorPayload,
    JoinRoomPayload,
    MessageType,
    PongPayload,
    RoomSnapshot,
    SeatSnapshot,
    WSClientMessage,
    WSCloseCode,
    WSServerMessage,
)
from app.services.room import get_room_service
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
                        payload=ErrorPayload(
                            error_code="INVALID_MESSAGE",
                            message="Invalid message format",
                        ).model_dump(),
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

            elif message.type == MessageType.CREATE_ROOM:
                logger.info(
                    "CREATE_ROOM request: connection=%s, user=%s, request_id=%s, payload=%s",
                    connection.connection_id,
                    user_id,
                    message.request_id,
                    message.payload,
                )

                # Validate request_id is required and is a valid UUID
                if not message.request_id:
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.CREATE_ROOM_ERROR,
                            payload=ErrorPayload(
                                error_code="VALIDATION_ERROR",
                                message="request_id is required",
                            ).model_dump(),
                        ),
                    )
                    continue

                try:
                    uuid.UUID(message.request_id)
                except ValueError:
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.CREATE_ROOM_ERROR,
                            request_id=message.request_id,
                            payload=ErrorPayload(
                                error_code="VALIDATION_ERROR",
                                message="request_id must be a valid UUID",
                            ).model_dump(),
                        ),
                    )
                    continue

                # Validate payload
                try:
                    payload = CreateRoomPayload.model_validate(message.payload or {})
                except ValidationError as e:
                    logger.warning(
                        "Invalid create_room payload from connection %s: %s",
                        connection.connection_id,
                        e,
                    )
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.CREATE_ROOM_ERROR,
                            request_id=message.request_id,
                            payload=ErrorPayload(
                                error_code="VALIDATION_ERROR",
                                message=str(e),
                            ).model_dump(),
                        ),
                    )
                    continue

                # Call room service
                room_service = get_room_service()
                result = await room_service.create_room(
                    user_id=user_id,
                    request_id=message.request_id,
                    visibility=payload.visibility,
                    max_players=payload.max_players,
                    ruleset_id=payload.ruleset_id,
                    ruleset_config=payload.ruleset_config,
                )

                if result.success:
                    # Validate required fields before constructing the OK payload
                    if (
                        result.room_id is None
                        or result.code is None
                        or result.seat_index is None
                        or result.is_host is None
                    ):
                        logger.error(
                            "CREATE_ROOM_OK result missing required fields: room_id=%s, code=%s, seat_index=%s, is_host=%s, user=%s, connection=%s",
                            result.room_id,
                            result.code,
                            result.seat_index,
                            result.is_host,
                            user_id,
                            connection.connection_id,
                        )
                        # Treat this as an internal error and notify the client
                        await manager.send_to_connection(
                            connection.connection_id,
                            WSServerMessage(
                                type=MessageType.CREATE_ROOM_ERROR,
                                request_id=message.request_id,
                                payload=ErrorPayload(
                                    error_code="INTERNAL_ERROR",
                                    message="Room creation succeeded but response was missing required data",
                                ).model_dump(),
                            ),
                        )
                    else:
                        # Subscribe connection to the room
                        await manager.subscribe_to_room(
                            connection.connection_id, result.room_id
                        )

                        # Fetch room snapshot for response
                        snapshot_data = await room_service.get_room_snapshot(result.room_id)
                        if not snapshot_data:
                            logger.error(
                                "Failed to get room snapshot after creation: room_id=%s",
                                result.room_id,
                            )
                            await manager.send_to_connection(
                                connection.connection_id,
                                WSServerMessage(
                                    type=MessageType.CREATE_ROOM_ERROR,
                                    request_id=message.request_id,
                                    payload=ErrorPayload(
                                        error_code="INTERNAL_ERROR",
                                        message="Room created but failed to retrieve snapshot",
                                    ).model_dump(),
                                ),
                            )
                            continue

                        # Convert dataclass snapshot to Pydantic model
                        room_snapshot = RoomSnapshot(
                            room_id=snapshot_data.room_id,
                            code=snapshot_data.code,
                            status=snapshot_data.status,
                            visibility=snapshot_data.visibility,
                            ruleset_id=snapshot_data.ruleset_id,
                            max_players=snapshot_data.max_players,
                            seats=[
                                SeatSnapshot(
                                    seat_index=seat.seat_index,
                                    user_id=seat.user_id,
                                    display_name=seat.display_name,
                                    ready=seat.ready,
                                    connected=seat.connected,
                                    is_host=seat.is_host,
                                )
                                for seat in snapshot_data.seats
                            ],
                            version=snapshot_data.version,
                        )

                        # Send success response with room snapshot
                        await manager.send_to_connection(
                            connection.connection_id,
                            WSServerMessage(
                                type=MessageType.CREATE_ROOM_OK,
                                request_id=message.request_id,
                                payload=room_snapshot.model_dump(),
                            ),
                        )
                        logger.info(
                            "CREATE_ROOM_OK: room_id=%s, code=%s, user=%s, connection=%s, cached=%s",
                            result.room_id,
                            result.code,
                            user_id,
                            connection.connection_id,
                            result.cached,
                        )
                else:
                    # Send error response
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.CREATE_ROOM_ERROR,
                            request_id=message.request_id,
                            payload=ErrorPayload(
                                error_code=result.error_code or "INTERNAL_ERROR",
                                message=result.error_message or "Unknown error",
                            ).model_dump(),
                        ),
                    )
                    logger.warning(
                        "CREATE_ROOM_ERROR: error_code=%s, message=%s, user=%s, connection=%s",
                        result.error_code,
                        result.error_message,
                        user_id,
                        connection.connection_id,
                    )

            elif message.type == MessageType.JOIN_ROOM:
                logger.info(
                    "JOIN_ROOM request: connection=%s, user=%s, request_id=%s, payload=%s",
                    connection.connection_id,
                    user_id,
                    message.request_id,
                    message.payload,
                )

                # Validate request_id is required and is a valid UUID
                if not message.request_id:
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.JOIN_ROOM_ERROR,
                            payload=ErrorPayload(
                                error_code="VALIDATION_ERROR",
                                message="request_id is required",
                            ).model_dump(),
                        ),
                    )
                    continue

                try:
                    uuid.UUID(message.request_id)
                except ValueError:
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.JOIN_ROOM_ERROR,
                            request_id=message.request_id,
                            payload=ErrorPayload(
                                error_code="VALIDATION_ERROR",
                                message="request_id must be a valid UUID",
                            ).model_dump(),
                        ),
                    )
                    continue

                # Validate payload
                try:
                    payload = JoinRoomPayload.model_validate(message.payload or {})
                except ValidationError as e:
                    logger.warning(
                        "Invalid join_room payload from connection %s: %s",
                        connection.connection_id,
                        e,
                    )
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.JOIN_ROOM_ERROR,
                            request_id=message.request_id,
                            payload=ErrorPayload(
                                error_code="VALIDATION_ERROR",
                                message=str(e),
                            ).model_dump(),
                        ),
                    )
                    continue

                # Call room service to join
                room_service = get_room_service()
                result = await room_service.join_room(
                    user_id=user_id,
                    room_code=payload.room_code,
                )

                if result.success and result.room_snapshot:
                    # Subscribe connection to the room
                    await manager.subscribe_to_room(
                        connection.connection_id, result.room_snapshot.room_id
                    )

                    # Convert dataclass snapshot to Pydantic model
                    snapshot = result.room_snapshot
                    room_snapshot = RoomSnapshot(
                        room_id=snapshot.room_id,
                        code=snapshot.code,
                        status=snapshot.status,
                        visibility=snapshot.visibility,
                        ruleset_id=snapshot.ruleset_id,
                        max_players=snapshot.max_players,
                        seats=[
                            SeatSnapshot(
                                seat_index=seat.seat_index,
                                user_id=seat.user_id,
                                display_name=seat.display_name,
                                ready=seat.ready,
                                connected=seat.connected,
                                is_host=seat.is_host,
                            )
                            for seat in snapshot.seats
                        ],
                        version=snapshot.version,
                    )

                    # Send success response with room snapshot
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.JOIN_ROOM_OK,
                            request_id=message.request_id,
                            payload=room_snapshot.model_dump(),
                        ),
                    )

                    # Broadcast room update to all other members
                    await manager.send_to_room(
                        result.room_snapshot.room_id,
                        WSServerMessage(
                            type=MessageType.ROOM_UPDATED,
                            payload=room_snapshot.model_dump(),
                        ),
                        exclude_connection=connection.connection_id,
                    )

                    logger.info(
                        "JOIN_ROOM_OK: room_id=%s, code=%s, user=%s, connection=%s",
                        result.room_snapshot.room_id,
                        payload.room_code,
                        user_id,
                        connection.connection_id,
                    )
                else:
                    # Send error response
                    await manager.send_to_connection(
                        connection.connection_id,
                        WSServerMessage(
                            type=MessageType.JOIN_ROOM_ERROR,
                            request_id=message.request_id,
                            payload=ErrorPayload(
                                error_code=result.error_code or "INTERNAL_ERROR",
                                message=result.error_message or "Unknown error",
                            ).model_dump(),
                        ),
                    )
                    logger.warning(
                        "JOIN_ROOM_ERROR: error_code=%s, message=%s, user=%s, connection=%s",
                        result.error_code,
                        result.error_message,
                        user_id,
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
