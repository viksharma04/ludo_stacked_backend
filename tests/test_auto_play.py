"""Tests for auto-play logic for disconnected players."""

from uuid import UUID

import pytest

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    PendingCapture,
    Player,
    Stack,
    StackState,
    Turn,
)
from app.services.game.auto_play import auto_play_turn, get_next_auto_action
from app.services.game.engine.actions import CaptureChoiceAction, MoveAction, RollAction

PLAYER_1_ID = UUID("00000000-0000-0000-0000-000000000001")
PLAYER_2_ID = UUID("00000000-0000-0000-0000-000000000002")


def _make_player(pid: UUID, name: str, color: str, turn_order: int, start: int) -> Player:
    return Player(
        player_id=pid,
        name=name,
        color=color,
        turn_order=turn_order,
        abs_starting_index=start,
        stacks=[Stack(stack_id=f"stack_{i}", state=StackState.HELL, height=1, progress=0) for i in range(1, 5)],
    )


def _make_board_setup() -> BoardSetup:
    return BoardSetup(
        grid_length=6,
        loop_length=52,
        squares_to_win=55,
        squares_to_homestretch=49,
        starting_positions=[0, 13, 26, 39],
        safe_spaces=[0, 7, 13, 20, 26, 33, 39, 46],
        get_out_rolls=[6],
    )


def _make_state(
    current_event: CurrentEvent = CurrentEvent.PLAYER_ROLL,
    rolls_to_allocate: list[int] | None = None,
    legal_moves: list[str] | None = None,
    pending_capture=None,
) -> GameState:
    players = [
        _make_player(PLAYER_1_ID, "P1", "red", 1, 0),
        _make_player(PLAYER_2_ID, "P2", "blue", 2, 13),
    ]
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=True,
        rolls_to_allocate=rolls_to_allocate or [],
        legal_moves=legal_moves or [],
        current_turn_order=1,
        extra_rolls=0,
        pending_capture=pending_capture,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=players,
        current_event=current_event,
        board_setup=_make_board_setup(),
        current_turn=turn,
        event_seq=10,
    )


class TestGetNextAutoAction:
    def test_returns_roll_action_for_player_roll(self) -> None:
        state = _make_state(current_event=CurrentEvent.PLAYER_ROLL)
        action = get_next_auto_action(state, PLAYER_1_ID)

        assert isinstance(action, RollAction)
        assert 1 <= action.value <= 6

    def test_returns_move_action_for_player_choice(self) -> None:
        # Player has a stack on ROAD that can move
        state = _make_state(
            current_event=CurrentEvent.PLAYER_CHOICE,
            rolls_to_allocate=[3],
            legal_moves=["stack_1"],
        )
        # Put stack_1 on ROAD so it has legal moves
        state.players[0].stacks[0] = Stack(
            stack_id="stack_1", state=StackState.ROAD, height=1, progress=0
        )
        action = get_next_auto_action(state, PLAYER_1_ID)

        assert isinstance(action, MoveAction)

    def test_returns_capture_choice_for_capture_choice(self) -> None:
        pending = PendingCapture(
            capturable_targets=[
                f"{PLAYER_2_ID}:stack_1",
                f"{PLAYER_2_ID}:stack_2",
            ],
            moving_stack_id="stack_1",
            position=0,
        )
        state = _make_state(
            current_event=CurrentEvent.CAPTURE_CHOICE,
            pending_capture=pending,
        )
        action = get_next_auto_action(state, PLAYER_1_ID)

        assert isinstance(action, CaptureChoiceAction)
        assert action.choice == f"{PLAYER_2_ID}:stack_1"  # First target


class TestAutoPlayTurn:
    def test_plays_full_turn_and_transitions(self) -> None:
        # All stacks in HELL, need a 6 to get out
        state = _make_state(current_event=CurrentEvent.PLAYER_ROLL)
        new_state, events = auto_play_turn(state, PLAYER_1_ID)

        # Turn should have transitioned to player 2 (or game state updated)
        # At minimum, events should include DiceRolled
        assert len(events) > 0
        dice_events = [e for e in events if e.event_type == "dice_rolled"]
        assert len(dice_events) >= 1

    def test_turn_ends_eventually(self) -> None:
        # Ensure auto_play_turn terminates (doesn't infinite loop)
        state = _make_state(current_event=CurrentEvent.PLAYER_ROLL)
        new_state, events = auto_play_turn(state, PLAYER_1_ID)

        # Turn must have ended — either next player's turn or game finished
        assert (
            new_state.current_turn.player_id != PLAYER_1_ID
            or new_state.phase == GamePhase.FINISHED
        )
