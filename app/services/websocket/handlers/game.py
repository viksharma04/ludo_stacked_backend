"""Handler for GAME_ACTION messages."""

import logging
from uuid import UUID

from app.schemas.ws import (
    GameActionPayload,
    GameErrorPayload,
    GameEventsPayload,
    MessageType,
    WSServerMessage,
)
from app.services.game.engine import (
    ProcessResult,
    build_action_from_payload,
)

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    require_authenticated,
    validate_payload,
)

logger = logging.getLogger(__name__)


# Placeholder for game state storage - will be replaced with Redis service
_game_states: dict[str, dict] = {}


async def get_game_state(room_id: str) -> dict | None:
    """Get game state for a room from storage.

    TODO: Replace with Redis-based game service.
    """
    return _game_states.get(room_id)


async def save_game_state(room_id: str, state: dict) -> None:
    """Save game state for a room to storage.

    TODO: Replace with Redis-based game service.
    """
    _game_states[room_id] = state


@handler(MessageType.GAME_ACTION)
async def handle_game_action(ctx: HandlerContext) -> HandlerResult:
    """Handle GAME_ACTION message by processing the action through the game engine.

    Flow:
    1. Validate authentication
    2. Validate payload
    3. Get current game state
    4. Build action from payload
    5. Process through game engine
    6. Save new state
    7. Broadcast events to room

    Returns:
        HandlerResult with events for requester and broadcast for room.
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
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    room_id = connection.room_id

    # Validate payload
    payload, validation_error = validate_payload(
        ctx.message.payload,
        GameActionPayload,
        ctx.message.request_id,
        MessageType.GAME_ERROR,
    )
    if validation_error:
        return validation_error

    # Get current game state
    game_state_dict = await get_game_state(room_id)
    if game_state_dict is None:
        return error_response(
            error_code="GAME_NOT_FOUND",
            message="No game in progress for this room",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Import here to avoid circular imports
    from app.schemas.game_engine import GameState

    try:
        game_state = GameState.model_validate(game_state_dict)
    except Exception:
        logger.exception("Failed to parse game state for room %s", room_id)
        return error_response(
            error_code="INVALID_GAME_STATE",
            message="Game state is corrupted",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Build action from payload
    try:
        action_dict = {
            "action_type": payload.action_type,
        }
        if payload.value is not None:
            action_dict["value"] = payload.value
        if payload.token_or_stack_id is not None:
            action_dict["token_or_stack_id"] = payload.token_or_stack_id
        if payload.choice is not None:
            action_dict["choice"] = payload.choice

        action = build_action_from_payload(action_dict)
    except ValueError as e:
        return error_response(
            error_code="INVALID_ACTION",
            message=str(e),
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Process through game engine
    from app.services.game.engine import process_action

    try:
        player_id = UUID(ctx.user_id)
    except ValueError:
        return error_response(
            error_code="INVALID_USER_ID",
            message="Invalid user ID format",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    result: ProcessResult = process_action(game_state, action, player_id)

    if not result.success:
        logger.info(
            "Game action failed for user %s in room %s: %s - %s",
            ctx.user_id,
            room_id,
            result.error_code,
            result.error_message,
        )
        return HandlerResult(
            success=False,
            response=WSServerMessage(
                type=MessageType.GAME_ERROR,
                request_id=ctx.message.request_id,
                payload=GameErrorPayload(
                    error_code=result.error_code or "PROCESSING_ERROR",
                    message=result.error_message or "Failed to process action",
                ).model_dump(),
            ),
        )

    # Save new state
    if result.state is not None:
        await save_game_state(room_id, result.state.model_dump())

    # Serialize events for broadcast
    serialized_events = [event.model_dump() for event in result.events]

    logger.info(
        "Game action processed for user %s in room %s: %d events",
        ctx.user_id,
        room_id,
        len(result.events),
    )

    # Return events to requester and broadcast to room
    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.GAME_EVENTS,
            request_id=ctx.message.request_id,
            payload=GameEventsPayload(events=serialized_events).model_dump(),
        ),
        broadcast=WSServerMessage(
            type=MessageType.GAME_EVENTS,
            payload=GameEventsPayload(events=serialized_events).model_dump(),
        ),
        room_id=room_id,
    )
