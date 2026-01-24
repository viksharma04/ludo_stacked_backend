"""Dice roll processing logic."""

from uuid import UUID

from app.schemas.game_engine import (
    CurrentEvent,
    GameState,
    Player,
    Turn,
)

from .events import (
    AnyGameEvent,
    AwaitingChoice,
    DiceRolled,
    ThreeSixesPenalty,
    TurnEnded,
    TurnStarted,
)
from .legal_moves import get_legal_moves
from .validation import ProcessResult


def create_new_turn(turn_order: int, players: list[Player]) -> Turn:
    """Create a new turn for the player with the given turn order."""
    player = next(p for p in players if p.turn_order == turn_order)
    return Turn(
        player_id=player.player_id,
        initial_roll=True,
        rolls_to_allocate=[],
        current_turn_order=player.turn_order,
        legal_moves=[],
        extra_rolls=0,
    )


def get_next_turn_order(current_order: int, num_players: int) -> int:
    """Calculate the next player's turn order (1-indexed, wrapping)."""
    return (current_order % num_players) + 1


def process_roll(state: GameState, roll_value: int, player_id: UUID) -> ProcessResult:
    """Process a dice roll and return updated state with events.

    Handles:
    - Adding roll to rolls_to_allocate
    - Three consecutive sixes penalty
    - Granting extra roll on 6
    - Transitioning to PLAYER_CHOICE if moves available
    - Ending turn if no legal moves

    Args:
        state: Current game state.
        roll_value: The dice value rolled (1-6).
        player_id: The player who rolled.

    Returns:
        ProcessResult with new state and events.
    """
    current_turn = state.current_turn
    if current_turn is None:
        return ProcessResult.failure("NO_ACTIVE_TURN", "No active turn")

    events: list[AnyGameEvent] = []

    # Add roll to the list
    new_rolls = [*current_turn.rolls_to_allocate, roll_value]
    roll_number = len(new_rolls)

    # Check for three consecutive sixes
    if len(new_rolls) >= 3 and all(r == 6 for r in new_rolls[-3:]):
        # Three sixes penalty - lose turn
        events.append(ThreeSixesPenalty(player_id=player_id, rolls=new_rolls[-3:]))

        next_turn_order = get_next_turn_order(
            current_turn.current_turn_order, len(state.players)
        )
        next_player = next(
            p for p in state.players if p.turn_order == next_turn_order
        )

        events.append(
            TurnEnded(
                player_id=player_id,
                reason="three_sixes",
                next_player_id=next_player.player_id,
            )
        )
        events.append(
            TurnStarted(player_id=next_player.player_id, turn_number=next_turn_order)
        )

        new_turn = create_new_turn(turn_order=next_turn_order, players=state.players)
        new_state = state.model_copy(
            update={
                "current_event": CurrentEvent.PLAYER_ROLL,
                "current_turn": new_turn,
            }
        )
        return ProcessResult.ok(new_state, events)

    # Record the dice roll event
    grants_extra = roll_value == 6
    events.append(
        DiceRolled(
            player_id=player_id,
            value=roll_value,
            roll_number=roll_number,
            grants_extra_roll=grants_extra,
        )
    )

    # Update turn with new roll
    updated_turn = current_turn.model_copy(
        update={
            "rolls_to_allocate": new_rolls,
            "initial_roll": False,
        }
    )

    # If rolled a 6, player gets another roll
    if roll_value == 6:
        new_state = state.model_copy(
            update={
                "current_event": CurrentEvent.PLAYER_ROLL,
                "current_turn": updated_turn,
            }
        )
        return ProcessResult.ok(new_state, events)

    # Check for legal moves with the first unallocated roll
    current_player = next(
        p for p in state.players if p.player_id == current_turn.player_id
    )
    legal_moves = get_legal_moves(current_player, new_rolls[0], state.board_setup)

    if legal_moves:
        # Transition to player choice
        updated_turn = updated_turn.model_copy(update={"legal_moves": legal_moves})
        events.append(
            AwaitingChoice(
                player_id=player_id,
                legal_moves=legal_moves,
                roll_to_allocate=new_rolls[0],
            )
        )
        new_state = state.model_copy(
            update={
                "current_event": CurrentEvent.PLAYER_CHOICE,
                "current_turn": updated_turn,
            }
        )
        return ProcessResult.ok(new_state, events)

    # No legal moves - end turn
    next_turn_order = get_next_turn_order(
        current_turn.current_turn_order, len(state.players)
    )
    next_player = next(p for p in state.players if p.turn_order == next_turn_order)

    events.append(
        TurnEnded(
            player_id=player_id,
            reason="no_legal_moves",
            next_player_id=next_player.player_id,
        )
    )
    events.append(
        TurnStarted(player_id=next_player.player_id, turn_number=next_turn_order)
    )

    new_turn = create_new_turn(turn_order=next_turn_order, players=state.players)
    new_state = state.model_copy(
        update={
            "current_event": CurrentEvent.PLAYER_ROLL,
            "current_turn": new_turn,
        }
    )
    return ProcessResult.ok(new_state, events)
