"""Handler for JOIN_ROOM messages."""

import logging

from app.schemas.ws import JoinRoomPayload, MessageType, WSServerMessage
from app.services.room import get_room_service

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    snapshot_to_pydantic,
    validate_payload,
    validate_request_id,
)

logger = logging.getLogger(__name__)


@handler(MessageType.JOIN_ROOM)
async def handle_join_room(ctx: HandlerContext) -> HandlerResult:
    """Handle JOIN_ROOM message."""
    logger.info(
        "JOIN_ROOM request: connection=%s, user=%s, request_id=%s, payload=%s",
        ctx.connection_id,
        ctx.user_id,
        ctx.message.request_id,
        ctx.message.payload,
    )

    # Validate request_id
    error = validate_request_id(ctx.message.request_id, MessageType.JOIN_ROOM_ERROR)
    if error:
        return error

    # Validate payload
    payload, error = validate_payload(
        ctx.message.payload,
        JoinRoomPayload,
        ctx.message.request_id,
        MessageType.JOIN_ROOM_ERROR,
    )
    if error:
        logger.warning(
            "Invalid join_room payload from connection %s",
            ctx.connection_id,
        )
        return error

    # Call room service
    room_service = get_room_service()
    result = await room_service.join_room(
        user_id=ctx.user_id,
        room_code=payload.room_code,
    )

    if not result.success or not result.room_snapshot:
        logger.warning(
            "JOIN_ROOM_ERROR: error_code=%s, message=%s, user=%s, connection=%s",
            result.error_code,
            result.error_message,
            ctx.user_id,
            ctx.connection_id,
        )
        return error_response(
            error_code=result.error_code or "INTERNAL_ERROR",
            message=result.error_message or "Unknown error",
            error_type=MessageType.JOIN_ROOM_ERROR,
            request_id=ctx.message.request_id,
        )

    # Subscribe connection to the room
    await ctx.manager.subscribe_to_room(
        ctx.connection_id,
        result.room_snapshot.room_id,
    )

    room_snapshot = snapshot_to_pydantic(result.room_snapshot)

    logger.info(
        "JOIN_ROOM_OK: room_id=%s, code=%s, user=%s, connection=%s",
        result.room_snapshot.room_id,
        payload.room_code,
        ctx.user_id,
        ctx.connection_id,
    )

    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.JOIN_ROOM_OK,
            request_id=ctx.message.request_id,
            payload=room_snapshot.model_dump(),
        ),
        broadcast=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            payload=room_snapshot.model_dump(),
        ),
        room_id=result.room_snapshot.room_id,
    )
