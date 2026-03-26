"""Auto-play logic for disconnected players.

Generates actions deterministically (first available move) and feeds them
through the normal engine pipeline. The engine stays untouched — this module
is just a caller that produces actions on behalf of a disconnected player.
"""

import logging
import random

from app.schemas.game_engine import CurrentEvent, GameState
from app.services.game.engine.actions import (
    CaptureChoiceAction,
    GameAction,
    MoveAction,
    RollAction,
)
from app.services.game.engine.events import AnyGameEvent
from app.services.game.engine.legal_moves import get_all_roll_move_groups
from app.services.game.engine.process import process_action

logger = logging.getLogger(__name__)


def get_next_auto_action(state: GameState, player_id) -> GameAction:
    """Inspect current game state and return the appropriate action.

    Selection strategy: always pick the first available option.
    - PLAYER_ROLL: random dice roll (1-6)
    - PLAYER_CHOICE: first RollMoveGroup -> first LegalMoveGroup -> first move ID
    - CAPTURE_CHOICE: first entry in pending_capture.capturable_targets
    """
    current_event = state.current_event
    turn = state.current_turn

    if current_event == CurrentEvent.PLAYER_ROLL:
        return RollAction(value=random.randint(1, 6))

    if current_event == CurrentEvent.PLAYER_CHOICE:
        player = next(p for p in state.players if p.player_id == player_id)
        roll_move_groups = get_all_roll_move_groups(
            player, turn.rolls_to_allocate, state.board_setup
        )
        # Pick first roll group -> first move group -> first move ID
        first_group = roll_move_groups[0]
        first_move_group = first_group.move_groups[0]
        first_move_id = first_move_group.moves[0]
        return MoveAction(stack_id=first_move_id, roll_value=first_group.roll)

    if current_event == CurrentEvent.CAPTURE_CHOICE:
        first_target = turn.pending_capture.capturable_targets[0]
        return CaptureChoiceAction(choice=first_target)

    msg = f"Unexpected current_event for auto-play: {current_event}"
    raise ValueError(msg)


def auto_play_turn(
    state: GameState,
    player_id,
) -> tuple[GameState, list[AnyGameEvent]]:
    """Auto-play a full turn for a disconnected player.

    Loops calling get_next_auto_action -> process_action until the turn
    transitions to a different player or the game ends.

    Returns:
        Tuple of (final_state, all_events_accumulated).
    """
    all_events: list[AnyGameEvent] = []
    current_state = state

    # Safety bound: a turn can have at most ~20 actions
    # (3 rolls max before penalty + moves + captures + extra rolls)
    max_iterations = 50

    for _ in range(max_iterations):
        # Check if turn has transitioned away from this player
        if current_state.current_turn is None:
            break
        if current_state.current_turn.player_id != player_id:
            break
        if current_state.phase.value == "finished":
            break

        action = get_next_auto_action(current_state, player_id)
        result = process_action(current_state, action, player_id)

        if not result.success:
            logger.error(
                "Auto-play action failed: %s — %s",
                result.error_code,
                result.error_message,
            )
            break

        all_events.extend(result.events)
        current_state = result.state

    logger.info(
        "Auto-played turn for player=%s: %d events",
        str(player_id)[:8],
        len(all_events),
    )

    return current_state, all_events
