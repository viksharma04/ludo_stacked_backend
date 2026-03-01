"""Integration tests for complete turn flows through process_action().

These tests simulate multi-step game sequences through the main process_action
entry point, verifying end-to-end behavior across rolls, moves, captures, and
turn transitions.

Updated for multi-roll allocation: MoveAction requires roll_value, and
AwaitingChoice uses available_moves (list of RollMoveGroup) instead of
roll_to_allocate + legal_moves.
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    StackState,
    Turn,
)
from app.services.game.engine.actions import MoveAction, RollAction, StartGameAction
from app.services.game.engine.events import (
    AwaitingChoice,
    DiceRolled,
    GameStarted,
    RollGranted,
    StackCaptured,
    StackExitedHell,
    StackMoved,
    ThreeSixesPenalty,
    TurnEnded,
    TurnStarted,
)
from app.services.game.engine.process import process_action
from tests.conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    PLAYER_3_ID,
    PLAYER_4_ID,
    create_player,
    create_stack,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def find_events(events, event_type):
    """Find all events of a specific type."""
    return [e for e in events if isinstance(e, event_type)]


def find_event(events, event_type):
    """Find first event of a specific type, or None."""
    matches = find_events(events, event_type)
    return matches[0] if matches else None


def get_rolls_offered(awaiting: AwaitingChoice) -> list[int]:
    """Get roll values that have moves in available_moves."""
    return [rmg.roll for rmg in awaiting.available_moves]


def get_moves_for_roll(awaiting: AwaitingChoice, roll: int) -> set[str]:
    """Get all move IDs offered for a specific roll value."""
    for rmg in awaiting.available_moves:
        if rmg.roll == roll:
            return {m for g in rmg.move_groups for m in g.moves}
    return set()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicTurnFlow:
    """Basic turn lifecycle: roll with no legal moves ends turn."""

    def test_complete_basic_turn_all_hell_non_six(self, standard_board_setup: BoardSetup):
        """All stacks in HELL, roll non-6 -> no legal moves -> turn passes."""
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26)
        turn = Turn(
            player_id=PLAYER_1_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=1,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        result = process_action(state, RollAction(value=3), PLAYER_1_ID)

        assert result.success
        assert result.state is not None

        # Should contain DiceRolled, TurnEnded, TurnStarted, RollGranted
        assert find_event(result.events, DiceRolled) is not None
        turn_ended = find_event(result.events, TurnEnded)
        assert turn_ended is not None
        assert turn_ended.reason == "no_legal_moves"
        assert turn_ended.next_player_id == PLAYER_2_ID
        assert find_event(result.events, TurnStarted) is not None
        assert find_event(result.events, RollGranted) is not None

        # New state should be player 2's turn
        assert result.state.current_turn is not None
        assert result.state.current_turn.player_id == PLAYER_2_ID
        assert result.state.current_event == CurrentEvent.PLAYER_ROLL


class TestExitHellFlow:
    """Roll a 6 to exit HELL, then use remaining roll to advance."""

    def test_exit_hell_then_move(self, standard_board_setup: BoardSetup):
        """Full flow: Roll 6 -> exit HELL -> use remaining roll to advance."""
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26)
        turn = Turn(
            player_id=PLAYER_1_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=1,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        # Step 1: Roll 6 -> gets extra roll (rolled a 6)
        result1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result1.success
        assert result1.state is not None
        assert result1.state.current_event == CurrentEvent.PLAYER_ROLL
        dice_rolled = find_event(result1.events, DiceRolled)
        assert dice_rolled is not None
        assert dice_rolled.grants_extra_roll is True
        roll_granted = find_event(result1.events, RollGranted)
        assert roll_granted is not None
        assert roll_granted.reason == "rolled_six"

        # Step 2: Roll 4 -> rolls_to_allocate=[6,4], AwaitingChoice
        result2 = process_action(result1.state, RollAction(value=4), PLAYER_1_ID)
        assert result2.success
        assert result2.state is not None
        assert result2.state.current_event == CurrentEvent.PLAYER_CHOICE
        awaiting = find_event(result2.events, AwaitingChoice)
        assert awaiting is not None
        # Roll 6 should be offered (can exit HELL)
        assert 6 in get_rolls_offered(awaiting)

        # Step 3: Move stack_1 to exit HELL using roll 6
        result3 = process_action(
            result2.state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result3.success
        assert result3.state is not None
        exited = find_event(result3.events, StackExitedHell)
        assert exited is not None
        assert exited.stack_id == "stack_1"
        # Remaining roll [4] -> recomputed, stack_1 on ROAD at progress=0
        awaiting2 = find_event(result3.events, AwaitingChoice)
        assert awaiting2 is not None
        assert 4 in get_rolls_offered(awaiting2)

        # Step 4: Move stack_1 forward by 4 (progress 0 -> 4) using roll 4
        result4 = process_action(
            result3.state, MoveAction(stack_id="stack_1", roll_value=4), PLAYER_1_ID
        )
        assert result4.success
        assert result4.state is not None
        moved = find_event(result4.events, StackMoved)
        assert moved is not None
        assert moved.stack_id == "stack_1"
        assert moved.from_progress == 0
        assert moved.to_progress == 4

        # Turn should have ended, passed to player 2
        turn_ended = find_event(result4.events, TurnEnded)
        assert turn_ended is not None
        assert turn_ended.next_player_id == PLAYER_2_ID

        # Final state: stack_1 at ROAD progress=4, player 2's turn
        p1_final = next(p for p in result4.state.players if p.player_id == PLAYER_1_ID)
        s1 = next(s for s in p1_final.stacks if s.stack_id == "stack_1")
        assert s1.state == StackState.ROAD
        assert s1.progress == 4
        assert result4.state.current_turn is not None
        assert result4.state.current_turn.player_id == PLAYER_2_ID


class TestDoubleSixFlow:
    """Roll two sixes then a non-six: exit two stacks, advance one."""

    def test_roll_double_six_then_non_six(self, standard_board_setup: BoardSetup):
        """Roll [6, 6, 3]: exit two stacks, advance one by 3."""
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26)
        turn = Turn(
            player_id=PLAYER_1_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=1,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        # Step 1: Roll 6 -> extra roll
        result1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result1.success
        assert result1.state is not None
        assert result1.state.current_event == CurrentEvent.PLAYER_ROLL

        # Step 2: Roll 6 -> extra roll
        result2 = process_action(result1.state, RollAction(value=6), PLAYER_1_ID)
        assert result2.success
        assert result2.state is not None
        assert result2.state.current_event == CurrentEvent.PLAYER_ROLL

        # Step 3: Roll 3 -> rolls=[6,6,3], AwaitingChoice
        result3 = process_action(result2.state, RollAction(value=3), PLAYER_1_ID)
        assert result3.success
        assert result3.state is not None
        assert result3.state.current_event == CurrentEvent.PLAYER_CHOICE
        awaiting = find_event(result3.events, AwaitingChoice)
        assert awaiting is not None
        assert 6 in get_rolls_offered(awaiting)

        # Step 4: Move stack_1 -> exits HELL using roll 6
        result4 = process_action(
            result3.state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result4.success
        assert result4.state is not None
        exited1 = find_event(result4.events, StackExitedHell)
        assert exited1 is not None
        assert exited1.stack_id == "stack_1"
        # Remaining [6, 3]: roll 6 should offer more HELL exits
        awaiting2 = find_event(result4.events, AwaitingChoice)
        assert awaiting2 is not None
        assert 6 in get_rolls_offered(awaiting2)

        # Step 5: Move stack_2 -> exits HELL using roll 6, merges with stack_1
        result5 = process_action(
            result4.state, MoveAction(stack_id="stack_2", roll_value=6), PLAYER_1_ID
        )
        assert result5.success
        assert result5.state is not None
        exited2 = find_event(result5.events, StackExitedHell)
        assert exited2 is not None
        assert exited2.stack_id == "stack_2"
        # Remaining [3]: split moves available
        awaiting3 = find_event(result5.events, AwaitingChoice)
        assert awaiting3 is not None
        assert 3 in get_rolls_offered(awaiting3)

        # Step 6: Split stack_2 from stack_1_2 and move forward by 3
        result6 = process_action(
            result5.state, MoveAction(stack_id="stack_2", roll_value=3), PLAYER_1_ID
        )
        assert result6.success
        assert result6.state is not None
        moved = find_event(result6.events, StackMoved)
        assert moved is not None
        assert moved.stack_id == "stack_2"
        assert moved.to_progress == 3

        # Turn should have ended
        turn_ended = find_event(result6.events, TurnEnded)
        assert turn_ended is not None

        # Final: stack_1 progress=0 ROAD, stack_2 progress=3 ROAD
        p1_final = next(p for p in result6.state.players if p.player_id == PLAYER_1_ID)
        s1 = next(s for s in p1_final.stacks if s.stack_id == "stack_1")
        s2 = next(s for s in p1_final.stacks if s.stack_id == "stack_2")
        assert s1.state == StackState.ROAD
        assert s1.progress == 0
        assert s2.state == StackState.ROAD
        assert s2.progress == 3


class TestThreeSixesPenaltyFlow:
    """Rolling three consecutive sixes triggers a penalty and ends the turn."""

    def test_three_sixes_penalty_ends_turn(self, standard_board_setup: BoardSetup):
        """Roll [6, 6, 6] -> penalty, no moves, turn passes."""
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26)
        turn = Turn(
            player_id=PLAYER_1_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=1,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        # Step 1: Roll 6 -> extra roll, rolls=[6]
        result1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result1.success
        assert result1.state is not None
        assert result1.state.current_event == CurrentEvent.PLAYER_ROLL

        # Step 2: Roll 6 -> extra roll, rolls=[6,6]
        result2 = process_action(result1.state, RollAction(value=6), PLAYER_1_ID)
        assert result2.success
        assert result2.state is not None
        assert result2.state.current_event == CurrentEvent.PLAYER_ROLL

        # Step 3: Roll 6 -> rolls=[6,6,6] -> ThreeSixesPenalty
        result3 = process_action(result2.state, RollAction(value=6), PLAYER_1_ID)
        assert result3.success
        assert result3.state is not None

        # ThreeSixesPenalty event should be present
        penalty = find_event(result3.events, ThreeSixesPenalty)
        assert penalty is not None
        assert penalty.player_id == PLAYER_1_ID
        assert penalty.rolls == [6, 6, 6]

        # TurnEnded with reason="three_sixes"
        turn_ended = find_event(result3.events, TurnEnded)
        assert turn_ended is not None
        assert turn_ended.reason == "three_sixes"
        assert turn_ended.next_player_id == PLAYER_2_ID

        # No moves should have been made - all stacks still in HELL
        assert find_event(result3.events, StackMoved) is None
        assert find_event(result3.events, StackExitedHell) is None

        # New turn for player 2
        assert result3.state.current_turn is not None
        assert result3.state.current_turn.player_id == PLAYER_2_ID
        assert result3.state.current_event == CurrentEvent.PLAYER_ROLL


class TestCaptureInTurnFlow:
    """Capturing an opponent's stack grants an extra roll."""

    def test_capture_during_turn_grants_extra_roll(self, standard_board_setup: BoardSetup):
        """Player 1 moves onto player 2's stack -> capture -> bonus roll."""
        # Player 1: stack_1 at ROAD progress=2 (abs = 0+2 = 2), others in HELL
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 2),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0, stacks=p1_stacks)

        # Player 2: stack_1 at ROAD progress=29 (abs = (26+29) % 50 = 5)
        # Position 5 is NOT a safe space (safe_spaces=[0, 10, 13, 23, 26, 36, 39, 49])
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26, stacks=p2_stacks)

        turn = Turn(
            player_id=PLAYER_1_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=1,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        # Step 1: Roll 3 -> AwaitingChoice with roll 3 moves for stack_1
        result1 = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result1.success
        assert result1.state is not None
        assert result1.state.current_event == CurrentEvent.PLAYER_CHOICE
        awaiting = find_event(result1.events, AwaitingChoice)
        assert awaiting is not None
        assert "stack_1" in get_moves_for_roll(awaiting, 3)

        # Step 2: Move stack_1 with roll 3 -> lands on position 5 -> captures
        result2 = process_action(
            result1.state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID
        )
        assert result2.success
        assert result2.state is not None

        # StackCaptured event
        captured = find_event(result2.events, StackCaptured)
        assert captured is not None
        assert captured.capturing_player_id == PLAYER_1_ID
        assert captured.captured_player_id == PLAYER_2_ID
        assert captured.grants_extra_roll is True

        # RollGranted for capture bonus
        roll_granted = find_event(result2.events, RollGranted)
        assert roll_granted is not None
        assert roll_granted.reason == "capture_bonus"

        # Player stays in PLAYER_ROLL for bonus roll
        assert result2.state.current_event == CurrentEvent.PLAYER_ROLL
        assert result2.state.current_turn is not None
        assert result2.state.current_turn.player_id == PLAYER_1_ID

        # Player 2's captured stack should be back in HELL
        p2_final = next(p for p in result2.state.players if p.player_id == PLAYER_2_ID)
        p2_s1 = next(s for s in p2_final.stacks if s.stack_id == "stack_1")
        assert p2_s1.state == StackState.HELL
        assert p2_s1.progress == 0


class TestGameStartSequence:
    """Starting a game emits the correct event sequence."""

    def test_start_game_emits_correct_event_sequence(self, two_player_game_not_started: GameState):
        """StartGameAction produces GameStarted, TurnStarted, RollGranted."""
        result = process_action(
            two_player_game_not_started,
            StartGameAction(),
            PLAYER_1_ID,
        )
        assert result.success
        assert result.state is not None
        assert result.state.phase == GamePhase.IN_PROGRESS

        # Check event ordering: GameStarted -> TurnStarted -> RollGranted
        event_types = [type(e) for e in result.events]
        assert event_types == [GameStarted, TurnStarted, RollGranted]

        game_started = find_event(result.events, GameStarted)
        assert game_started is not None
        assert game_started.first_player_id == PLAYER_1_ID
        assert PLAYER_1_ID in game_started.player_order
        assert PLAYER_2_ID in game_started.player_order

        turn_started = find_event(result.events, TurnStarted)
        assert turn_started is not None
        assert turn_started.player_id == PLAYER_1_ID

        roll_granted = find_event(result.events, RollGranted)
        assert roll_granted is not None
        assert roll_granted.player_id == PLAYER_1_ID
        assert roll_granted.reason == "turn_start"


class TestTurnWrapping:
    """Turn order wraps from last player back to first."""

    def test_turn_wraps_from_player4_to_player1(self, standard_board_setup: BoardSetup):
        """4-player game, player 4's turn, roll non-6 -> wraps to player 1."""
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 13)
        player3 = create_player(PLAYER_3_ID, "Player 3", "green", 3, 26)
        player4 = create_player(PLAYER_4_ID, "Player 4", "yellow", 4, 39)

        turn = Turn(
            player_id=PLAYER_4_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=4,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2, player3, player4],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        # Roll 3 -> no legal moves (all in HELL) -> turn ends
        result = process_action(state, RollAction(value=3), PLAYER_4_ID)
        assert result.success
        assert result.state is not None

        turn_ended = find_event(result.events, TurnEnded)
        assert turn_ended is not None
        assert turn_ended.next_player_id == PLAYER_1_ID

        assert result.state.current_turn is not None
        assert result.state.current_turn.player_id == PLAYER_1_ID
        assert result.state.current_turn.current_turn_order == 1


class TestMultiActionSequence:
    """Verify current_event transitions at each step of a multi-action turn."""

    def test_multi_action_sequence_through_process_action(self, standard_board_setup: BoardSetup):
        """
        Full sequence verifying event transitions:
        1. Roll 6 (extra roll) -> PLAYER_ROLL
        2. Roll 2 (rolls=[6,2]) -> PLAYER_CHOICE (available_moves for 6)
        3. Move (exit HELL, roll_value=6) -> PLAYER_CHOICE (available_moves for 2)
        4. Move (advance 2, roll_value=2) -> turn ends
        """
        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26)
        turn = Turn(
            player_id=PLAYER_1_ID,
            initial_roll=True,
            rolls_to_allocate=[],
            legal_moves=[],
            current_turn_order=1,
            extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=standard_board_setup,
            current_turn=turn,
        )

        # Step 1: Roll 6 -> extra roll -> PLAYER_ROLL
        result1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result1.success
        assert result1.state is not None
        assert result1.state.current_event == CurrentEvent.PLAYER_ROLL

        # Step 2: Roll 2 -> rolls=[6,2] -> PLAYER_CHOICE
        result2 = process_action(result1.state, RollAction(value=2), PLAYER_1_ID)
        assert result2.success
        assert result2.state is not None
        assert result2.state.current_event == CurrentEvent.PLAYER_CHOICE
        awaiting = find_event(result2.events, AwaitingChoice)
        assert awaiting is not None
        assert 6 in get_rolls_offered(awaiting)

        # Step 3: Move stack_1 -> exits HELL with roll 6 -> PLAYER_CHOICE (roll 2)
        result3 = process_action(
            result2.state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result3.success
        assert result3.state is not None
        assert result3.state.current_event == CurrentEvent.PLAYER_CHOICE
        exited = find_event(result3.events, StackExitedHell)
        assert exited is not None
        assert exited.stack_id == "stack_1"
        awaiting2 = find_event(result3.events, AwaitingChoice)
        assert awaiting2 is not None
        assert 2 in get_rolls_offered(awaiting2)

        # Step 4: Move stack_1 by 2 with roll 2 -> turn ends -> PLAYER_ROLL (next player)
        result4 = process_action(
            result3.state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID
        )
        assert result4.success
        assert result4.state is not None
        assert result4.state.current_event == CurrentEvent.PLAYER_ROLL
        moved = find_event(result4.events, StackMoved)
        assert moved is not None
        assert moved.to_progress == 2
        turn_ended = find_event(result4.events, TurnEnded)
        assert turn_ended is not None
        assert turn_ended.reason == "all_rolls_used"
        assert turn_ended.next_player_id == PLAYER_2_ID
