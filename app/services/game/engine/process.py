"""Main entry point for game action processing.

This module provides the primary interface for processing game actions:
- process_action(): Validates and processes any game action
- Dispatches to specialized handlers based on action type
- Returns ProcessResult with new state and events
"""

from uuid import UUID

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
from .events import AnyGameEvent, GameStarted, TurnStarted
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
    # Validate the action
    validation = validate_action(state, action, player_id)
    if not validation.is_valid:
        return ProcessResult.failure(
            validation.error_code or "VALIDATION_ERROR",
            validation.error_message or "Invalid action",
        )

    # Dispatch to appropriate handler
    if isinstance(action, StartGameAction):
        result = process_start_game(state)

    elif isinstance(action, RollAction):
        result = process_roll(state, action.value, player_id)

    elif isinstance(action, MoveAction):
        result = process_move(state, action.token_or_stack_id, player_id)

    elif isinstance(action, CaptureChoiceAction):
        result = process_capture_choice(state, action.choice, player_id)
        if result.state is None:
            return ProcessResult.failure(
                "CAPTURE_CHOICE_FAILED", "Failed to process capture choice"
            )

    else:
        return ProcessResult.failure(
            "UNKNOWN_ACTION",
            f"Unknown action type: {type(action).__name__}",
        )

    # Assign sequence numbers to events and update state
    if result.success and result.state is not None:
        result = _assign_event_sequences(result)

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
    events: list[AnyGameEvent] = []

    # Create first turn
    new_turn = create_new_turn(turn_order=1, players=state.players)

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

    new_state = state.model_copy(
        update={
            "phase": GamePhase.IN_PROGRESS,
            "current_event": CurrentEvent.PLAYER_ROLL,
            "current_turn": new_turn,
        }
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
        if all(token.state == TokenState.HEAVEN for token in player.tokens):
            return player.player_id
    return None
