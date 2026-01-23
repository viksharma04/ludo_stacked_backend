"""Handler for TOGGLE_READY messages."""

import logging

from app.schemas.ws import MessageType, WSServerMessage
from app.services.room.service import get_room_service

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    require_authenticated,
    snapshot_to_pydantic,
)

logger = logging.getLogger(__name__)


@handler(MessageType.TOGGLE_READY)
async def handle_toggle_ready(ctx: HandlerContext) -> HandlerResult:
    """Handle TOGGLE_READY message by toggling the user's ready state.

    Returns room snapshot to requester and broadcasts to all room members.
    """
    # Require authentication
    auth_error = require_authenticated(ctx)
    if auth_error:
        return auth_error

    # Get connection to find room_id
    connection = ctx.manager.get_connection(ctx.connection_id)
    if connection is None or connection.room_id is None:
        return error_response(
            error_code="NOT_IN_ROOM",
            message="You are not in a room",
            error_type=MessageType.ERROR,
            request_id=ctx.message.request_id,
        )

    room_id = connection.room_id
    room_service = get_room_service()

    # Toggle ready
    result = await room_service.toggle_ready(room_id, ctx.user_id)

    if not result.success:
        return error_response(
            error_code=result.error_code or "INTERNAL_ERROR",
            message=result.error_message or "Failed to toggle ready",
            error_type=MessageType.ERROR,
            request_id=ctx.message.request_id,
        )

    # Get fresh room snapshot
    snapshot = await room_service.get_room_snapshot(room_id)
    if not snapshot:
        return error_response(
            error_code="ROOM_NOT_FOUND",
            message="Room not found",
            error_type=MessageType.ERROR,
            request_id=ctx.message.request_id,
        )

    pydantic_snapshot = snapshot_to_pydantic(snapshot)

    logger.info(
        "User %s toggled ready to %s in room %s",
        ctx.user_id,
        result.new_ready_state,
        room_id,
    )

    # Return response to requester and broadcast to all room members
    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            request_id=ctx.message.request_id,
            payload=pydantic_snapshot.model_dump(),
        ),
        broadcast=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            payload=pydantic_snapshot.model_dump(),
        ),
        room_id=room_id,
    )
