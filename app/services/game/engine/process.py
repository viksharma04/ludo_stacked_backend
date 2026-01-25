"""Main entry point for game action processing.

This module provides the primary interface for processing game actions:
- process_action(): Validates and processes any game action
- Dispatches to specialized handlers based on action type
- Returns ProcessResult with new state and events
"""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)

from app.schemas.game_engine import (
    CurrentEvent,
    GamePhase,
    GameState,
)

from .actions import (
    CaptureChoiceAction,
    GameAction,
    MoveAction,
    RollAction,
    StartGameAction,
)
from .captures import process_capture_choice
from .events import AnyGameEvent, GameStarted, RollGranted, TurnStarted
from .movement import process_move
from .rolling import create_new_turn, process_roll
from .validation import ProcessResult, validate_action


def process_action(
    state: GameState,
    action: GameAction,
    player_id: UUID,
) -> ProcessResult:
    """Process a game action and return the result.

    This is the main entry point for all game actions. It:
    1. Validates the action is legal given current state
    2. Dispatches to the appropriate handler
    3. Assigns sequence numbers to events
    4. Returns ProcessResult with new state and events

    Args:
        state: Current game state.
        action: The action to process.
        player_id: The player attempting the action.

    Returns:
        ProcessResult containing:
        - success: Whether the action was processed successfully
        - state: The new game state (if successful)
        - events: List of events that occurred (with seq numbers)
        - error_code/error_message: Error details (if failed)

    Example:
        >>> result = process_action(state, RollAction(value=6), player_id)
        >>> if result.success:
        ...     new_state = result.state
        ...     for event in result.events:
        ...         broadcast(event)  # event.seq is set
        ... else:
        ...     send_error(result.error_code, result.error_message)
    """
    action_type = type(action).__name__
    logger.info(
        "Processing action: type=%s, player=%s, phase=%s",
        action_type,
        player_id,
        state.phase.value,
    )
    logger.debug("Action details: %s", action)

    # Validate the action
    validation = validate_action(state, action, player_id)
    if not validation.is_valid:
        logger.warning(
            "Action validation failed: code=%s, message=%s, player=%s, action=%s",
            validation.error_code,
            validation.error_message,
            player_id,
            action_type,
        )
        return ProcessResult.failure(
            validation.error_code or "VALIDATION_ERROR",
            validation.error_message or "Invalid action",
        )

    # Dispatch to appropriate handler
    logger.debug("Dispatching to handler for action type: %s", action_type)

    if isinstance(action, StartGameAction):
        result = process_start_game(state)

    elif isinstance(action, RollAction):
        result = process_roll(state, action.value, player_id)

    elif isinstance(action, MoveAction):
        result = process_move(state, action.token_or_stack_id, player_id)

    elif isinstance(action, CaptureChoiceAction):
        result = process_capture_choice(state, action.choice, player_id)
        if result.state is None:
            logger.error("Capture choice failed: player=%s, choice=%s", player_id, action.choice)
            return ProcessResult.failure(
                "CAPTURE_CHOICE_FAILED", "Failed to process capture choice"
            )

    else:
        logger.error("Unknown action type received: %s", action_type)
        return ProcessResult.failure(
            "UNKNOWN_ACTION",
            f"Unknown action type: {type(action).__name__}",
        )

    # Assign sequence numbers to events and update state
    if result.success and result.state is not None:
        result = _assign_event_sequences(result)
        logger.info(
            "Action processed successfully: type=%s, player=%s, events_generated=%d",
            action_type,
            player_id,
            len(result.events),
        )
        logger.debug("Generated events: %s", [type(e).__name__ for e in result.events])
    else:
        logger.warning(
            "Action processing failed: type=%s, player=%s, error=%s",
            action_type,
            player_id,
            result.error_code,
        )

    return result


def _assign_event_sequences(result: ProcessResult) -> ProcessResult:
    """Assign monotonically increasing sequence numbers to events.

    Updates each event's seq field and increments the state's event_seq counter.
    """
    if result.state is None or not result.events:
        return result

    current_seq = result.state.event_seq
    for event in result.events:
        event.seq = current_seq
        current_seq += 1

    # Update state with new sequence counter
    new_state = result.state.model_copy(update={"event_seq": current_seq})

    return ProcessResult.ok(new_state, result.events)


def process_start_game(state: GameState) -> ProcessResult:
    """Transition game from NOT_STARTED to IN_PROGRESS.

    Creates the first turn and sets up initial game state.

    Args:
        state: Current game state (must be NOT_STARTED).

    Returns:
        ProcessResult with game in IN_PROGRESS phase.
    """
    logger.info("Starting game with %d players", len(state.players))
    events: list[AnyGameEvent] = []

    # Create first turn
    new_turn = create_new_turn(turn_order=1, players=state.players)
    logger.debug("Created first turn for player with turn_order=1")

    # Get player order for the event
    player_order = [
        p.player_id for p in sorted(state.players, key=lambda p: p.turn_order)
    ]
    first_player_id = (
        next(p.player_id for p in state.players if p.turn_order == 1)
        if state.players
        else player_order[0]
    )

    events.append(
        GameStarted(
            player_order=player_order,
            first_player_id=first_player_id,
        )
    )
    events.append(TurnStarted(player_id=first_player_id, turn_number=1))
    events.append(RollGranted(player_id=first_player_id, reason="turn_start"))

    new_state = state.model_copy(
        update={
            "phase": GamePhase.IN_PROGRESS,
            "current_event": CurrentEvent.PLAYER_ROLL,
            "current_turn": new_turn,
        }
    )

    logger.info(
        "Game started: first_player=%s, player_order=%s",
        first_player_id,
        [str(pid)[:8] for pid in player_order],
    )
    return ProcessResult.ok(new_state, events)


def check_win_condition(state: GameState) -> UUID | None:
    """Check if any player has won the game.

    A player wins when all their tokens are in HEAVEN.

    Args:
        state: Current game state.

    Returns:
        The winning player's UUID, or None if no winner yet.
    """
    from app.schemas.game_engine import TokenState

    for player in state.players:
        tokens_in_heaven = sum(1 for t in player.tokens if t.state == TokenState.HEAVEN)
        logger.debug(
            "Win check: player=%s, tokens_in_heaven=%d/%d",
            str(player.player_id)[:8],
            tokens_in_heaven,
            len(player.tokens),
        )
        if all(token.state == TokenState.HEAVEN for token in player.tokens):
            logger.info("Winner detected: player=%s", player.player_id)
            return player.player_id
    return None
