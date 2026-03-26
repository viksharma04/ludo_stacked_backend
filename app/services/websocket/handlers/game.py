"""Handler for GAME_ACTION messages."""

import asyncio
import logging
from uuid import UUID

from app.config import get_settings
from app.schemas.game_engine import GameState
from app.schemas.ws import (
    GameActionPayload,
    GameEventsPayload,
    MessageType,
    WSServerMessage,
)
from app.services.game import ProcessResult, build_action_from_payload, process_action
from app.services.game.auto_play import auto_play_turn
from app.services.game.state import get_game_state, save_game_state
from app.services.room.service import get_room_service

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    require_authenticated,
    validate_payload,
)

logger = logging.getLogger(__name__)


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
        if payload.stack_id is not None:
            action_dict["stack_id"] = payload.stack_id
        if payload.roll_value is not None:
            action_dict["roll_value"] = payload.roll_value
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
        return error_response(
            error_code=result.error_code or "PROCESSING_ERROR",
            message=result.error_message or "Failed to process action",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Save new state
    if result.state is not None:
        await save_game_state(room_id, result.state.model_dump(mode="json"))

    # Serialize events for broadcast
    serialized_events = [event.model_dump(mode="json") for event in result.events]

    logger.info(
        "Game action processed for user %s in room %s: %d events",
        ctx.user_id,
        room_id,
        len(result.events),
    )

    # Build initial response and broadcast
    response = WSServerMessage(
        type=MessageType.GAME_EVENTS,
        request_id=ctx.message.request_id,
        payload=GameEventsPayload(events=serialized_events).model_dump(),
    )
    broadcast = WSServerMessage(
        type=MessageType.GAME_EVENTS,
        payload=GameEventsPayload(events=serialized_events).model_dump(),
    )

    # Check for disconnected player auto-move
    if result.state is not None and result.state.phase.value == "in_progress":
        auto_events, auto_played_ids = await _auto_play_disconnected_turns(
            room_id, result.state, ctx
        )
        if auto_events:
            # Mark TurnStarted in original events for auto-played players
            for d in serialized_events:
                if (
                    d.get("event_type") == "turn_started"
                    and d.get("player_id") in auto_played_ids
                ):
                    d["auto_played"] = True
            # Append auto-play events to the broadcast
            all_events = serialized_events + auto_events
            broadcast = WSServerMessage(
                type=MessageType.GAME_EVENTS,
                payload=GameEventsPayload(events=all_events).model_dump(),
            )
            response = WSServerMessage(
                type=MessageType.GAME_EVENTS,
                request_id=ctx.message.request_id,
                payload=GameEventsPayload(events=all_events).model_dump(),
            )

    return HandlerResult(
        success=True,
        response=response,
        broadcast=broadcast,
        room_id=room_id,
    )


async def _auto_play_disconnected_turns(
    room_id: str,
    current_state: "GameState",
    ctx: HandlerContext,
) -> tuple[list[dict], set[str]]:
    """Check if current player is disconnected and auto-play their turn after grace period.

    Returns tuple of (serialized auto-play events, set of auto-played player ID strings).
    Handles consecutive disconnected players.
    """
    all_auto_events: list[dict] = []
    auto_played_ids: set[str] = set()
    state = current_state
    max_auto_plays = len(state.players)  # Safety: don't auto-play more than full rotation

    for _ in range(max_auto_plays):
        if state.current_turn is None:
            break
        if state.phase.value == "finished":
            break

        current_player_id = state.current_turn.player_id
        current_player_id_str = str(current_player_id)

        # Check if current player is connected
        room_service = get_room_service()
        snapshot = await room_service.get_room_snapshot(room_id)
        if snapshot is None:
            break

        player_connected = any(
            seat.user_id == current_player_id_str and seat.connected
            for seat in snapshot.seats
        )

        if player_connected:
            break

        # Grace period
        settings = get_settings()
        await asyncio.sleep(settings.TURN_SKIP_GRACE_PERIOD)

        # Re-check after grace period
        snapshot = await room_service.get_room_snapshot(room_id)
        if snapshot is None:
            break

        player_connected = any(
            seat.user_id == current_player_id_str and seat.connected
            for seat in snapshot.seats
        )

        if player_connected:
            break

        auto_played_ids.add(current_player_id_str)

        # Auto-play this player's turn
        state, events = auto_play_turn(state, current_player_id)

        event_dicts = [event.model_dump(mode="json") for event in events]
        all_auto_events.extend(event_dicts)

        # Save updated state
        await save_game_state(room_id, state.model_dump(mode="json"))

        logger.info(
            "Auto-played disconnected player %s turn in room %s",
            current_player_id_str[:8],
            room_id,
        )

    # Mark TurnStarted events only for players who were actually auto-played
    for d in all_auto_events:
        if (
            d.get("event_type") == "turn_started"
            and d.get("player_id") in auto_played_ids
        ):
            d["auto_played"] = True

    return all_auto_events, auto_played_ids
