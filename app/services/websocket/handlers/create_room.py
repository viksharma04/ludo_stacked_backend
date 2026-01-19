"""Handler for CREATE_ROOM messages."""

import logging

from app.schemas.ws import CreateRoomPayload, MessageType, WSServerMessage
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


@handler(MessageType.CREATE_ROOM)
async def handle_create_room(ctx: HandlerContext) -> HandlerResult:
    """Handle CREATE_ROOM message."""
    logger.info(
        "CREATE_ROOM request: connection=%s, user=%s, request_id=%s, payload=%s",
        ctx.connection_id,
        ctx.user_id,
        ctx.message.request_id,
        ctx.message.payload,
    )

    # Validate request_id
    error = validate_request_id(ctx.message.request_id, MessageType.CREATE_ROOM_ERROR)
    if error:
        return error

    # Validate payload
    payload, error = validate_payload(
        ctx.message.payload,
        CreateRoomPayload,
        ctx.message.request_id,
        MessageType.CREATE_ROOM_ERROR,
    )
    if error:
        logger.warning(
            "Invalid create_room payload from connection %s",
            ctx.connection_id,
        )
        return error

    # Call room service
    room_service = get_room_service()
    result = await room_service.create_room(
        user_id=ctx.user_id,
        request_id=ctx.message.request_id,
        visibility=payload.visibility,
        max_players=payload.max_players,
        ruleset_id=payload.ruleset_id,
        ruleset_config=payload.ruleset_config,
    )

    if not result.success:
        logger.warning(
            "CREATE_ROOM_ERROR: error_code=%s, message=%s, user=%s, connection=%s",
            result.error_code,
            result.error_message,
            ctx.user_id,
            ctx.connection_id,
        )
        return error_response(
            error_code=result.error_code or "INTERNAL_ERROR",
            message=result.error_message or "Unknown error",
            error_type=MessageType.CREATE_ROOM_ERROR,
            request_id=ctx.message.request_id,
        )

    # Validate required fields
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
            ctx.user_id,
            ctx.connection_id,
        )
        return error_response(
            error_code="INTERNAL_ERROR",
            message="Room creation succeeded but response was missing required data",
            error_type=MessageType.CREATE_ROOM_ERROR,
            request_id=ctx.message.request_id,
        )

    # Subscribe connection to the room
    await ctx.manager.subscribe_to_room(ctx.connection_id, result.room_id)

    # Fetch room snapshot
    snapshot_data = await room_service.get_room_snapshot(result.room_id)
    if not snapshot_data:
        logger.error(
            "Failed to get room snapshot after creation: room_id=%s",
            result.room_id,
        )
        return error_response(
            error_code="INTERNAL_ERROR",
            message="Room created but failed to retrieve snapshot",
            error_type=MessageType.CREATE_ROOM_ERROR,
            request_id=ctx.message.request_id,
        )

    room_snapshot = snapshot_to_pydantic(snapshot_data)

    logger.info(
        "CREATE_ROOM_OK: room_id=%s, code=%s, user=%s, connection=%s, cached=%s",
        result.room_id,
        result.code,
        ctx.user_id,
        ctx.connection_id,
        result.cached,
    )

    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.CREATE_ROOM_OK,
            request_id=ctx.message.request_id,
            payload=room_snapshot.model_dump(),
        ),
    )
