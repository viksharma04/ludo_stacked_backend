"""Handler for LEAVE_ROOM messages."""

import logging

from app.schemas.ws import MessageType, RoomClosedPayload, WSServerMessage
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


@handler(MessageType.LEAVE_ROOM)
async def handle_leave_room(ctx: HandlerContext) -> HandlerResult:
    """Handle LEAVE_ROOM message.

    If host leaves: close room, broadcast ROOM_CLOSED to all.
    If player leaves: clear seat, broadcast ROOM_UPDATED to remaining players.
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

    # Leave room
    result = await room_service.leave_room(room_id, ctx.user_id)

    if not result.success:
        return error_response(
            error_code=result.error_code or "INTERNAL_ERROR",
            message=result.error_message or "Failed to leave room",
            error_type=MessageType.ERROR,
            request_id=ctx.message.request_id,
        )

    # Unsubscribe from room (clear room_id on connection)
    await ctx.manager.unsubscribe_from_room(ctx.connection_id)

    if result.room_closed:
        # Host left - broadcast ROOM_CLOSED to remaining players
        logger.info("Host %s left room %s, broadcasting room_closed", ctx.user_id, room_id)

        return HandlerResult(
            success=True,
            response=WSServerMessage(
                type=MessageType.ROOM_CLOSED,
                request_id=ctx.message.request_id,
                payload=RoomClosedPayload(
                    reason="host_left",
                    room_id=room_id,
                ).model_dump(),
            ),
            broadcast=WSServerMessage(
                type=MessageType.ROOM_CLOSED,
                payload=RoomClosedPayload(
                    reason="host_left",
                    room_id=room_id,
                ).model_dump(),
            ),
            room_id=room_id,
        )

    # Player left - broadcast ROOM_UPDATED to remaining players
    if result.room_snapshot:
        pydantic_snapshot = snapshot_to_pydantic(result.room_snapshot)

        logger.info("Player %s left room %s", ctx.user_id, room_id)

        return HandlerResult(
            success=True,
            response=WSServerMessage(
                type=MessageType.ROOM_UPDATED,
                request_id=ctx.message.request_id,
                payload=None,
            ),
            broadcast=WSServerMessage(
                type=MessageType.ROOM_UPDATED,
                payload=pydantic_snapshot.model_dump(),
            ),
            room_id=room_id,
        )

    # Fallback - shouldn't happen but return success
    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            request_id=ctx.message.request_id,
            payload=None,
        ),
    )
