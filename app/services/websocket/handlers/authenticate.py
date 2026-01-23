"""Handler for WebSocket authentication messages."""

import logging

from app.schemas.ws import (
    AuthenticatePayload,
    MessageType,
    WSServerMessage,
)
from app.services.room.service import get_room_service
from app.services.websocket.auth import get_ws_authenticator

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    snapshot_to_pydantic,
    validate_payload,
)

logger = logging.getLogger(__name__)


@handler(MessageType.AUTHENTICATE)
async def handle_authenticate(ctx: HandlerContext) -> HandlerResult:
    """Handle authentication request from client.

    Client sends: { type: "authenticate", payload: { token: "...", room_code: "ABC123" } }

    On success: Authenticates connection, subscribes to room, sends room snapshot.
    On failure: Sends error response (connection remains open but unauthenticated).
    """
    # Check if already authenticated
    connection = ctx.manager.get_connection(ctx.connection_id)
    if connection is None:
        return error_response(
            "CONNECTION_NOT_FOUND",
            "Connection not found",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    if connection.authenticated:
        return error_response(
            "ALREADY_AUTHENTICATED",
            "Connection is already authenticated",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    # Validate payload
    payload, error = validate_payload(
        ctx.message.payload,
        AuthenticatePayload,
        ctx.message.request_id,
        MessageType.ERROR,
    )
    if error:
        return error

    # Validate token
    authenticator = get_ws_authenticator()
    auth_result = await authenticator.validate_token(payload.token)

    if not auth_result.success:
        error_code = "AUTH_EXPIRED" if auth_result.expired else "AUTH_FAILED"
        logger.warning(
            "Authentication failed for connection %s: %s",
            ctx.connection_id,
            auth_result.error,
        )
        return error_response(
            error_code,
            auth_result.error or "Authentication failed",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    user_id = auth_result.payload.get("sub") if auth_result.payload else None
    if not user_id:
        logger.warning(
            "Authentication failed for connection %s: missing user_id in token",
            ctx.connection_id,
        )
        return error_response(
            "AUTH_FAILED",
            "Invalid token: missing user_id",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    # Validate room access
    room_service = get_room_service()
    room_id, error_msg = await room_service.validate_room_access(user_id, payload.room_code)
    if error_msg:
        logger.warning(
            "Room access denied for user %s, connection %s: %s (room_code=%s)",
            user_id,
            ctx.connection_id,
            error_msg,
            payload.room_code,
        )
        error_code = "ROOM_NOT_FOUND" if error_msg == "ROOM_NOT_FOUND" else "ROOM_ACCESS_DENIED"
        return error_response(
            error_code,
            f"Room access denied: {error_msg}",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    # Update seat connected status
    await room_service.update_seat_connected_by_user(room_id, user_id, connected=True)

    # Get fresh room snapshot
    room_snapshot_data = await room_service.get_room_snapshot(room_id)
    if not room_snapshot_data:
        logger.error("Room %s not found in Redis after auth succeeded", room_id)
        return error_response(
            "ROOM_NOT_FOUND",
            "Room not found",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    room_snapshot = snapshot_to_pydantic(room_snapshot_data)

    # Authenticate the connection (this sends the AUTHENTICATED message)
    success = await ctx.manager.authenticate_connection(
        ctx.connection_id, user_id, room_id, room_snapshot
    )
    if not success:
        return error_response(
            "AUTH_FAILED",
            "Failed to authenticate connection",
            MessageType.ERROR,
            ctx.message.request_id,
        )

    logger.info(
        "Connection %s authenticated for user %s in room %s",
        ctx.connection_id,
        user_id,
        payload.room_code,
    )

    # Broadcast room update to other members
    return HandlerResult(
        success=True,
        response=None,  # AUTHENTICATED message already sent by authenticate_connection
        broadcast=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            payload=room_snapshot.model_dump(),
        ),
        room_id=room_id,
    )
