"""Handler for START_GAME messages."""

import logging
from uuid import UUID

from app.schemas.game_engine import GameSettings, PlayerAttributes
from app.schemas.ws import (
    GameStartedPayload,
    MessageType,
    WSServerMessage,
)
from app.services.game import StartGameAction, initialize_game, process_action
from app.services.room.service import RoomSnapshotData, get_room_service

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    require_authenticated,
)
from .game import get_game_state, save_game_state

logger = logging.getLogger(__name__)

# Standard Ludo colors mapped to seat indices
SEAT_COLORS = ["red", "blue", "green", "yellow"]


def _build_game_settings_from_room(room_snapshot: RoomSnapshotData) -> GameSettings:
    """Build GameSettings from room snapshot data.

    Maps occupied seats to player attributes with predefined colors.

    Args:
        room_snapshot: The room snapshot containing seat data.

    Returns:
        GameSettings ready for initialize_game().

    Raises:
        ValueError: If room has fewer than 2 players.
    """
    player_attributes = []

    for seat in room_snapshot.seats:
        if seat.user_id is not None:
            player_attributes.append(
                PlayerAttributes(
                    player_id=UUID(seat.user_id),
                    name=seat.display_name or f"Player {seat.seat_index + 1}",
                    color=SEAT_COLORS[seat.seat_index],
                )
            )

    if len(player_attributes) < 2:
        raise ValueError("At least 2 players are required to start the game")

    return GameSettings(
        num_players=len(player_attributes),
        player_attributes=player_attributes,
        grid_length=6,
        get_out_rolls=[6],
    )


@handler(MessageType.START_GAME)
async def handle_start_game(ctx: HandlerContext) -> HandlerResult:
    """Handle START_GAME message from the host to begin the game.

    Flow:
    1. Validate authentication
    2. Validate user is in a room
    3. Get room snapshot
    4. Validate user is the host
    5. Validate room status is "ready_to_start"
    6. Build game settings from room seats
    7. Initialize game state
    8. Process StartGameAction to transition to IN_PROGRESS
    9. Save game state
    10. Update room status to "in_game"
    11. Return response to host and broadcast events to room

    Returns:
        HandlerResult with game state for host and events broadcast for room.
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
    room_service = get_room_service()

    # Get room snapshot
    room_snapshot = await room_service.get_room_snapshot(room_id)
    if room_snapshot is None:
        return error_response(
            error_code="ROOM_NOT_FOUND",
            message="Room not found",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Find user's seat and check if they're the host
    user_seat = None
    for seat in room_snapshot.seats:
        if seat.user_id == ctx.user_id:
            user_seat = seat
            break

    if user_seat is None:
        return error_response(
            error_code="NOT_SEATED",
            message="You don't have a seat in this room",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    if not user_seat.is_host:
        return error_response(
            error_code="NOT_HOST",
            message="Only the host can start the game",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Check room status
    if room_snapshot.status == "open":
        return error_response(
            error_code="PLAYERS_NOT_READY",
            message="All players must be ready before starting the game",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    if room_snapshot.status == "in_game":
        return error_response(
            error_code="GAME_ALREADY_STARTED",
            message="Game has already started",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    if room_snapshot.status != "ready_to_start":
        return error_response(
            error_code="INVALID_ROOM_STATE",
            message=f"Cannot start game from room status '{room_snapshot.status}'",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Check if a game already exists for this room
    existing_state = await get_game_state(room_id)
    if existing_state is not None:
        return error_response(
            error_code="GAME_ALREADY_STARTED",
            message="A game is already in progress for this room",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Build game settings from room seats
    try:
        game_settings = _build_game_settings_from_room(room_snapshot)
    except ValueError as e:
        return error_response(
            error_code="GAME_INIT_FAILED",
            message=str(e),
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Initialize game state (phase=NOT_STARTED)
    try:
        game_state = initialize_game(game_settings)
    except ValueError as e:
        logger.exception("Failed to initialize game for room %s", room_id)
        return error_response(
            error_code="GAME_INIT_FAILED",
            message=str(e),
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Process StartGameAction to transition to IN_PROGRESS
    host_id = UUID(ctx.user_id)
    result = process_action(game_state, StartGameAction(), host_id)

    if not result.success:
        logger.error(
            "Failed to process StartGameAction for room %s: %s - %s",
            room_id,
            result.error_code,
            result.error_message,
        )
        return error_response(
            error_code=result.error_code or "GAME_START_FAILED",
            message=result.error_message or "Failed to start game",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    if result.state is None:
        return error_response(
            error_code="GAME_START_FAILED",
            message="Game state was not created",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    # Save game state
    await save_game_state(room_id, result.state.model_dump())

    # Update room status to in_game
    await room_service.update_room_status_to_in_game(room_id)

    # Serialize events and state for broadcast
    serialized_events = [event.model_dump() for event in result.events]
    serialized_state = result.state.model_dump()

    logger.info(
        "Game started for room %s by host %s: %d events, %d players",
        room_id,
        ctx.user_id,
        len(result.events),
        len(result.state.players),
    )

    # Broadcast GAME_STARTED with full state to ALL players so they can render UI
    # The host also receives this as their response (with request_id)
    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.GAME_STARTED,
            request_id=ctx.message.request_id,
            payload=GameStartedPayload(
                game_state=serialized_state,
                events=serialized_events,
            ).model_dump(),
        ),
        broadcast=WSServerMessage(
            type=MessageType.GAME_STARTED,
            payload=GameStartedPayload(
                game_state=serialized_state,
                events=serialized_events,
            ).model_dump(),
        ),
        room_id=room_id,
    )
