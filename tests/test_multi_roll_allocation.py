"""Tests for multi-roll allocation mechanics.

Intended rules:
- Player sees legal moves for ALL accumulated rolls in a single AwaitingChoice event
- AwaitingChoice.available_moves is a list of RollMoveGroup, one per usable roll value
- Rolls with no legal moves are silently excluded from available_moves
- Player chooses both which roll to use AND which stack to move via MoveAction(stack_id, roll_value)
- After each move, legal moves are recomputed against the new board state
- Capture bonus rolls are deferred until all accumulated rolls are consumed
- Turn only ends when NO accumulated roll has legal moves

Schema changes from the old API:
- AwaitingChoice.available_moves: list[RollMoveGroup] replaces legal_moves + roll_to_allocate
- MoveAction.roll_value: int (new field) — specifies which roll to consume
- RollMoveGroup(roll: int, move_groups: list[LegalMoveGroup]) — new model
"""

from uuid import UUID

import pytest

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Player,
    RollMoveGroup,
    Stack,
    StackState,
    Turn,
)
from app.services.game.engine.process import process_action
from app.services.game.engine.actions import RollAction, MoveAction
from app.services.game.engine.events import (
    DiceRolled,
    AwaitingChoice,
    RollGranted,
    TurnEnded,
    TurnStarted,
    StackExitedHell,
    StackMoved,
)
from app.services.game.engine.legal_moves import get_legal_moves
from tests.conftest import (
    create_stack,
    create_player,
    create_stacks_in_hell,
    PLAYER_1_ID,
    PLAYER_2_ID,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_two_player_game(
    player1_stacks,
    player2_stacks,
    board_setup,
    rolls=None,
    legal_moves=None,
    current_event=CurrentEvent.PLAYER_ROLL,
    extra_rolls=0,
):
    """Build a two-player game state with Player 1's turn active."""
    player1 = create_player(
        PLAYER_1_ID, "Player 1", "red", 1, 0, stacks=player1_stacks
    )
    player2 = create_player(
        PLAYER_2_ID, "Player 2", "blue", 2, 26, stacks=player2_stacks
    )
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=False,
        rolls_to_allocate=rolls or [],
        legal_moves=legal_moves or [],
        current_turn_order=1,
        extra_rolls=extra_rolls,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=current_event,
        board_setup=board_setup,
        current_turn=turn,
    )


def find_awaiting(events) -> AwaitingChoice | None:
    """Find the first AwaitingChoice event, or None."""
    return next((e for e in events if isinstance(e, AwaitingChoice)), None)


def get_rolls_offered(awaiting: AwaitingChoice) -> list[int]:
    """Get the roll values that have moves available."""
    return [rmg.roll for rmg in awaiting.available_moves]


def get_moves_for_roll(awaiting: AwaitingChoice, roll: int) -> set[str]:
    """Get all move IDs offered for a specific roll value."""
    for rmg in awaiting.available_moves:
        if rmg.roll == roll:
            return {m for g in rmg.move_groups for m in g.moves}
    return set()


def get_all_moves(awaiting: AwaitingChoice) -> set[str]:
    """Get all move IDs across all rolls."""
    return {
        m
        for rmg in awaiting.available_moves
        for g in rmg.move_groups
        for m in g.moves
    }


# ---------------------------------------------------------------------------
# 1. Combined view: all accumulated rolls shown in AwaitingChoice
# ---------------------------------------------------------------------------


class TestCombinedRollView:
    """AwaitingChoice should present legal moves for ALL accumulated rolls,
    each in its own RollMoveGroup."""

    def test_both_rolls_shown_when_both_have_legal_moves(
        self, standard_board_setup: BoardSetup
    ):
        """Player has stack_1 on ROAD at progress=10, stacks 2-4 in HELL.
        Accumulated rolls: [6, 3].

        Roll 6: stack_1 can move (advance 6) AND stacks 2-4 can exit HELL.
        Roll 3: stack_1 can move (advance 3).

        AwaitingChoice.available_moves should contain RollMoveGroups for BOTH
        roll 6 and roll 3, so the player can choose any (roll, stack) pair.
        """
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        # Accumulate [6] then roll 3 to trigger choice phase
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        assert result.state is not None
        assert result.state.current_event == CurrentEvent.PLAYER_CHOICE

        awaiting = find_awaiting(result.events)
        assert awaiting is not None

        # Both rolls should appear in available_moves
        offered_rolls = get_rolls_offered(awaiting)
        assert 6 in offered_rolls, "Roll 6 should be in available_moves"
        assert 3 in offered_rolls, "Roll 3 should be in available_moves"

        # Roll 6 should include HELL exits AND road move
        moves_for_6 = get_moves_for_roll(awaiting, 6)
        assert "stack_1" in moves_for_6, "stack_1 can advance 6 on ROAD"
        assert "stack_2" in moves_for_6, "stack_2 can exit HELL with 6"
        assert "stack_3" in moves_for_6, "stack_3 can exit HELL with 6"
        assert "stack_4" in moves_for_6, "stack_4 can exit HELL with 6"

        # Roll 3 should include only road move
        moves_for_3 = get_moves_for_roll(awaiting, 3)
        assert "stack_1" in moves_for_3, "stack_1 can advance 3 on ROAD"
        assert "stack_2" not in moves_for_3, "HELL stacks cannot exit with 3"

    def test_rolls_without_legal_moves_excluded(
        self, standard_board_setup: BoardSetup
    ):
        """All stacks in HELL, rolls = [3, 6, 2].
        Only roll 6 has legal moves. Rolls 3 and 2 should NOT appear in
        available_moves — they are silently excluded.
        """
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        # Accumulate [3, 6] then roll 2
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[3],
            current_event=CurrentEvent.PLAYER_ROLL,
        )
        # Roll 6 → extra roll granted
        r1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert r1.success and r1.state is not None
        assert r1.state.current_turn.rolls_to_allocate == [3, 6]

        # Roll 2 → rolls=[3, 6, 2], engine evaluates
        r2 = process_action(r1.state, RollAction(value=2), PLAYER_1_ID)
        assert r2.success and r2.state is not None

        awaiting = find_awaiting(r2.events)
        assert awaiting is not None, (
            "Should emit AwaitingChoice because roll 6 has legal moves"
        )

        offered_rolls = get_rolls_offered(awaiting)
        assert 6 in offered_rolls, "Roll 6 should appear (can exit HELL)"
        assert 3 not in offered_rolls, "Roll 3 should be excluded (no moves)"
        assert 2 not in offered_rolls, "Roll 2 should be excluded (no moves)"

    def test_available_moves_contain_legal_move_groups(
        self, standard_board_setup: BoardSetup
    ):
        """Verify the RollMoveGroup structure has proper LegalMoveGroups
        with parent stack grouping."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        awaiting = find_awaiting(result.events)
        assert awaiting is not None

        # Each RollMoveGroup should have move_groups (list of LegalMoveGroup)
        for rmg in awaiting.available_moves:
            assert isinstance(rmg, RollMoveGroup)
            assert isinstance(rmg.roll, int)
            assert len(rmg.move_groups) > 0
            for group in rmg.move_groups:
                assert isinstance(group.stack_id, str)
                assert isinstance(group.moves, list)
                assert len(group.moves) > 0


# ---------------------------------------------------------------------------
# 2. MoveAction with roll_value
# ---------------------------------------------------------------------------


class TestMoveActionWithRollValue:
    """MoveAction now requires roll_value to specify which roll to consume."""

    def test_move_consumes_specified_roll(
        self, standard_board_setup: BoardSetup
    ):
        """Using roll_value=6 removes exactly one 6 from rolls_to_allocate."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 4],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 using roll 6
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result.success
        assert result.state is not None

        # Roll 6 consumed, only roll 4 remains
        assert result.state.current_turn is not None
        assert result.state.current_turn.rolls_to_allocate == [4]

    def test_player_can_choose_non_first_roll(
        self, standard_board_setup: BoardSetup
    ):
        """Player chooses roll 4 instead of roll 6. Roll 4 consumed, 6 remains."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 4],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 using roll 4 (not the first roll!)
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=4), PLAYER_1_ID
        )
        assert result.success
        assert result.state is not None

        # stack_1 should have moved by 4 (progress 10 -> 14)
        moved = [e for e in result.events if isinstance(e, StackMoved)]
        assert len(moved) == 1
        assert moved[0].to_progress == 14

        # Roll 4 consumed, roll 6 remains
        assert result.state.current_turn.rolls_to_allocate == [6]

        # AwaitingChoice should show moves for remaining roll 6
        awaiting = find_awaiting(result.events)
        assert awaiting is not None
        assert 6 in get_rolls_offered(awaiting)

    def test_invalid_roll_value_not_in_pool(
        self, standard_board_setup: BoardSetup
    ):
        """roll_value not in rolls_to_allocate returns error, state unchanged."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 4],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Try to use roll 5, which is not in the pool
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=5), PLAYER_1_ID
        )
        assert not result.success
        assert result.state is None or result.state == state

    def test_stack_not_legal_for_specified_roll(
        self, standard_board_setup: BoardSetup
    ):
        """Stack that is not a legal move for the specified roll returns error."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 4],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # stack_2 is in HELL; roll 4 cannot exit HELL (only 6 can)
        result = process_action(
            state, MoveAction(stack_id="stack_2", roll_value=4), PLAYER_1_ID
        )
        assert not result.success


# ---------------------------------------------------------------------------
# 3. Duplicate rolls
# ---------------------------------------------------------------------------


class TestDuplicateRolls:
    """Handling of duplicate roll values in the pool."""

    def test_consume_one_of_duplicate_rolls(
        self, standard_board_setup: BoardSetup
    ):
        """rolls=[6, 6, 3], MoveAction with roll_value=6 -> remaining [6, 3]."""
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 6, 3],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Exit stack_1 from HELL using one of the two 6s
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result.success
        assert result.state is not None

        # One 6 consumed: remaining should be [6, 3]
        assert result.state.current_turn.rolls_to_allocate == [6, 3]

    def test_duplicate_rolls_deduplicated_in_available_moves(
        self, standard_board_setup: BoardSetup
    ):
        """rolls=[6, 6] with all in HELL: available_moves should have
        one entry for roll 6 (not two identical entries)."""
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        # Build state right before choice phase
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        # Roll 6 again → extra roll, but then we need a non-6 to trigger choice.
        # Actually with [6, 6] both are 6s so rolling continues.
        # Let's use [6, 6, 3] and check the initial AwaitingChoice.
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 6],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        # Roll 3 to finalize → rolls=[6, 6, 3]
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        awaiting = find_awaiting(result.events)
        assert awaiting is not None

        # Roll 6 should appear exactly once (deduplicated)
        rolls_with_6 = [rmg for rmg in awaiting.available_moves if rmg.roll == 6]
        assert len(rolls_with_6) == 1, (
            "Duplicate roll values should be deduplicated in available_moves"
        )


# ---------------------------------------------------------------------------
# 4. Recomputation after each move
# ---------------------------------------------------------------------------


class TestRecomputationAfterMove:
    """Legal moves are recomputed against the new board state after each move."""

    def test_hell_exit_enables_road_moves_for_remaining_rolls(
        self, standard_board_setup: BoardSetup
    ):
        """After exiting HELL with roll 6, remaining roll 4 can now move
        the stack that just landed on ROAD.

        Before the move: stack_1 in HELL, roll 4 has no legal moves.
        After the move: stack_1 on ROAD at progress=0, roll 4 can advance it.
        """
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        # Accumulate rolls [6, 4] via rolling
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        # Roll 6 → extra roll
        r1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert r1.success and r1.state is not None
        assert r1.state.current_turn.rolls_to_allocate == [6]

        # Roll 4 → rolls=[6, 4], engine evaluates
        r2 = process_action(r1.state, RollAction(value=4), PLAYER_1_ID)
        assert r2.success and r2.state is not None
        assert r2.state.current_event == CurrentEvent.PLAYER_CHOICE

        # Initial AwaitingChoice: roll 6 has moves (HELL exit), roll 4 doesn't
        awaiting1 = find_awaiting(r2.events)
        assert awaiting1 is not None
        assert 6 in get_rolls_offered(awaiting1)
        # Roll 4 shouldn't have moves (all in HELL)
        assert 4 not in get_rolls_offered(awaiting1)

        # Exit stack_1 from HELL using roll 6
        r3 = process_action(
            r2.state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert r3.success and r3.state is not None

        exit_events = [e for e in r3.events if isinstance(e, StackExitedHell)]
        assert len(exit_events) == 1

        # After recomputation, roll 4 NOW has legal moves (stack_1 on ROAD)
        awaiting2 = find_awaiting(r3.events)
        assert awaiting2 is not None, (
            "After HELL exit, remaining roll 4 should offer moves"
        )
        assert 4 in get_rolls_offered(awaiting2)
        assert "stack_1" in get_moves_for_roll(awaiting2, 4)

    def test_merge_changes_legal_moves(
        self, standard_board_setup: BoardSetup
    ):
        """After two stacks merge (stacking), legal moves reflect the
        new height. A roll that was divisible by height=1 may not be
        divisible by height=2.
        """
        # stack_1 on ROAD at progress=0, stack_2 on ROAD at progress=3
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 0),
            create_stack("stack_2", StackState.ROAD, 1, 3),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        # rolls=[3, 4]: roll 3 can move stack_2 to progress=6 or stack_1 to 3
        # Moving stack_1 with roll 3 → progress=3, merges with stack_2 → stack_1_2 (height=2)
        # Remaining roll 4: stack_1_2 height=2, 4%2==0, effective=2 → can move
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[3, 4],
            legal_moves=["stack_1", "stack_2"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 with roll 3 → merges with stack_2 at progress=3
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID
        )
        assert result.success and result.state is not None

        # After merge, recomputed moves for roll 4:
        # stack_1_2 (height=2, progress=3): 4%2==0, effective=2, progress 3→5
        awaiting = find_awaiting(result.events)
        assert awaiting is not None
        assert 4 in get_rolls_offered(awaiting)
        moves_for_4 = get_moves_for_roll(awaiting, 4)
        assert "stack_1_2" in moves_for_4, (
            "Merged stack should be movable with remaining roll"
        )


# ---------------------------------------------------------------------------
# 5. Skip rolls with no legal moves
# ---------------------------------------------------------------------------


class TestSkipRollNoLegalMoves:
    """Rolls with no legal moves are silently excluded from AwaitingChoice.
    Turn only ends when NO roll has legal moves."""

    def test_usable_roll_offered_when_others_have_no_moves(
        self, standard_board_setup: BoardSetup
    ):
        """All stacks in HELL, accumulated [3, 6, 2].
        Roll 3 and 2 have no legal moves. Roll 6 does.
        Turn should NOT end; AwaitingChoice should show only roll 6.
        """
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        # Start with [3], roll 6 → extra roll, roll 2 → rolls=[3, 6, 2]
        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[3],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        r1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert r1.success and r1.state is not None
        assert r1.state.current_turn.rolls_to_allocate == [3, 6]

        r2 = process_action(r1.state, RollAction(value=2), PLAYER_1_ID)
        assert r2.success and r2.state is not None

        turn_ended = [e for e in r2.events if isinstance(e, TurnEnded)]
        assert len(turn_ended) == 0, "Turn should NOT end when roll 6 has moves"

        awaiting = find_awaiting(r2.events)
        assert awaiting is not None
        offered_rolls = get_rolls_offered(awaiting)
        assert 6 in offered_rolls
        assert 3 not in offered_rolls
        assert 2 not in offered_rolls

    def test_turn_ends_only_when_all_rolls_have_no_legal_moves(
        self, standard_board_setup: BoardSetup
    ):
        """All stacks in HELL, single roll of 3. No roll has legal moves.
        Turn should end.
        """
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success and result.state is not None

        turn_ended = [e for e in result.events if isinstance(e, TurnEnded)]
        assert len(turn_ended) == 1
        assert turn_ended[0].reason == "no_legal_moves"
        assert result.state.current_turn.player_id == PLAYER_2_ID

    def test_unusable_rolls_silently_discarded_after_move(
        self, standard_board_setup: BoardSetup
    ):
        """After a move, if remaining rolls have no legal moves, they are
        discarded and the turn ends (or extra rolls kick in).

        rolls=[6, 2], stack_1 on ROAD at progress=53.
        Move stack_1 with roll 6 → progress=53 is invalid (53+6=59 > 55).
        Actually, let's use: stack_1 ROAD progress=10, roll 6 → progress=16.
        Remaining roll 2: stack_1 can advance 2 → 18. But if stacks 2-4 in HELL,
        roll 2 can't exit. So only stack_1 uses roll 2.

        Better scenario: stack_1 at HOMESTRETCH progress=53.
        Roll 2 → progress 55 (HEAVEN!). Roll 1 → progress 54 (legal).
        Move with roll 2 → HEAVEN. Remaining roll 1 → stack_1 is gone,
        stacks 2-4 in HELL → roll 1 has no moves → turn ends.
        """
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 53),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[2, 1],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 with roll 2 → progress 53+2=55 → HEAVEN
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID
        )
        assert result.success and result.state is not None

        # Remaining roll [1]: no moves (stack_1 in HEAVEN, rest in HELL)
        # Roll 1 silently discarded, turn ends
        turn_ended = [e for e in result.events if isinstance(e, TurnEnded)]
        assert len(turn_ended) == 1
        assert turn_ended[0].reason == "all_rolls_used" or turn_ended[0].reason == "no_legal_moves"


# ---------------------------------------------------------------------------
# 6. Bonus roll ordering
# ---------------------------------------------------------------------------


class TestBonusRollOrdering:
    """Capture bonus rolls are deferred until all accumulated rolls consumed."""

    def test_remaining_rolls_before_bonus_roll(
        self, standard_board_setup: BoardSetup
    ):
        """Player has rolls=[6, 4]. Uses roll 6, captures opponent.
        extra_rolls += 1. But remaining roll [4] should be offered FIRST
        before entering PLAYER_ROLL for the bonus.
        """
        # Player 1: stack_1 on ROAD at progress=2
        # Player 2: stack_1 on ROAD at progress=34 (abs = (26+34)%52 = 8)
        # Wait, let me compute this correctly.
        # Player 1 abs_starting_index=0, stack at progress=2 → abs_pos = (0+2) % num_squares
        # Player 2 abs_starting_index=26, stack at progress=29 → abs_pos = (26+29) % 52 = 3
        # Hmm, the board has starting_positions [0, 13, 26, 39], so total squares on
        # the main loop = 4 * 13 = 52.
        # Player 1 progress=2 → abs = (0+2) % 52 = 2
        # For capture: Player 2 must have a stack at abs position 8 (not safe)
        # Player 2 abs_starting_index=26, progress=p → abs = (26+p) % 52
        # We want abs = 8 → 26+p ≡ 8 (mod 52) → p = -18 mod 52 = 34
        # Player 1 needs to land at abs 8: progress 0→8 with roll 6 → progress=6? No.
        # Progress = 2, roll 6 → progress = 8. abs_pos = (0+8) % 52 = 8. Good.
        # Position 8 is NOT a safe space (safe = [0,10,13,23,26,36,39,49]).

        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 2),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 34),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_two_player_game(
            player1_stacks=p1_stacks,
            player2_stacks=p2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 4],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 with roll 6: progress 2→8, captures P2's stack at abs 8
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result.success and result.state is not None

        # Capture grants extra_rolls, but remaining roll [4] should be offered first
        assert result.state.current_event == CurrentEvent.PLAYER_CHOICE, (
            "Should be PLAYER_CHOICE for remaining roll 4, not PLAYER_ROLL for bonus"
        )
        assert result.state.current_turn.extra_rolls >= 1, (
            "extra_rolls should be incremented from capture"
        )

        awaiting = find_awaiting(result.events)
        assert awaiting is not None
        assert 4 in get_rolls_offered(awaiting)

    def test_bonus_roll_after_all_rolls_consumed(
        self, standard_board_setup: BoardSetup
    ):
        """Player captures with their LAST roll. No remaining rolls.
        Should enter PLAYER_ROLL for the capture bonus.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 2),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 34),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_two_player_game(
            player1_stacks=p1_stacks,
            player2_stacks=p2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 with roll 6: captures, no remaining rolls
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result.success and result.state is not None

        # No remaining rolls → enters PLAYER_ROLL for bonus
        assert result.state.current_event == CurrentEvent.PLAYER_ROLL
        roll_granted = [e for e in result.events if isinstance(e, RollGranted)]
        assert any(rg.reason == "capture_bonus" for rg in roll_granted)


# ---------------------------------------------------------------------------
# 7. Multiple moves in a single turn
# ---------------------------------------------------------------------------


class TestMultipleMovesInTurn:
    """Multi-step turn flows with explicit roll selection."""

    def test_exit_hell_then_move_same_stack(
        self, standard_board_setup: BoardSetup
    ):
        """Full integration through process_action.

        Player 1 has all stacks in HELL.
        1. Roll 6 → extra roll granted
        2. Roll 4 → rolls=[6, 4], AwaitingChoice with available_moves
        3. MoveAction(stack_id="stack_1", roll_value=6) → exits HELL, progress=0
        4. Remaining roll [4] recomputed: stack_1 on ROAD → movable
        5. MoveAction(stack_id="stack_1", roll_value=4) → progress=4

        Final state: stack_1 at ROAD progress=4.
        """
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        # Step 1: Roll 6 → extra roll
        r1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert r1.success and r1.state is not None
        assert r1.state.current_event == CurrentEvent.PLAYER_ROLL
        assert r1.state.current_turn.rolls_to_allocate == [6]

        roll_granted = [e for e in r1.events if isinstance(e, RollGranted)]
        assert any(rg.reason == "rolled_six" for rg in roll_granted)

        # Step 2: Roll 4 → rolls=[6, 4], AwaitingChoice
        r2 = process_action(r1.state, RollAction(value=4), PLAYER_1_ID)
        assert r2.success and r2.state is not None
        assert r2.state.current_turn.rolls_to_allocate == [6, 4]
        assert r2.state.current_event == CurrentEvent.PLAYER_CHOICE

        awaiting1 = find_awaiting(r2.events)
        assert awaiting1 is not None
        # Roll 6 has HELL exits, roll 4 doesn't (all in HELL)
        assert 6 in get_rolls_offered(awaiting1)
        assert "stack_1" in get_moves_for_roll(awaiting1, 6)

        # Step 3: Exit stack_1 from HELL with roll 6
        r3 = process_action(
            r2.state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert r3.success and r3.state is not None

        exit_events = [e for e in r3.events if isinstance(e, StackExitedHell)]
        assert len(exit_events) == 1
        assert exit_events[0].stack_id == "stack_1"

        # After HELL exit, remaining [4], recomputed: stack_1 on ROAD can move
        assert r3.state.current_event == CurrentEvent.PLAYER_CHOICE
        assert r3.state.current_turn.rolls_to_allocate == [4]

        awaiting2 = find_awaiting(r3.events)
        assert awaiting2 is not None
        assert 4 in get_rolls_offered(awaiting2)
        assert "stack_1" in get_moves_for_roll(awaiting2, 4)

        # Step 4: Move stack_1 with roll 4 → progress=4
        r4 = process_action(
            r3.state, MoveAction(stack_id="stack_1", roll_value=4), PLAYER_1_ID
        )
        assert r4.success and r4.state is not None

        moved = [e for e in r4.events if isinstance(e, StackMoved)]
        assert len(moved) == 1
        assert moved[0].stack_id == "stack_1"
        assert moved[0].to_progress == 4

        # Turn should end
        turn_ended = [e for e in r4.events if isinstance(e, TurnEnded)]
        assert len(turn_ended) == 1

        # Verify final stack state
        final_p1 = next(p for p in r4.state.players if p.player_id == PLAYER_1_ID)
        s1 = next(s for s in final_p1.stacks if s.stack_id == "stack_1")
        assert s1.state == StackState.ROAD
        assert s1.progress == 4

    def test_two_stacks_exit_hell_with_double_six(
        self, standard_board_setup: BoardSetup
    ):
        """Player 1 has all stacks in HELL.

        1. Roll 6 → extra roll
        2. Roll 6 → extra roll
        3. Roll 3 → rolls=[6, 6, 3], AwaitingChoice
        4. MoveAction(stack_id="stack_1", roll_value=6) → exits HELL
        5. Remaining [6, 3]: roll 6 can exit more HELL stacks
        6. MoveAction(stack_id="stack_2", roll_value=6) → exits HELL,
           merges with stack_1 at progress=0 → stack_1_2 (height=2)
        7. Remaining [3]: stack_1_2 height=2, 3%2!=0, but split: stack_2 (height=1)
           can move 3. So "stack_2" is a legal move for roll 3.
        8. MoveAction(stack_id="stack_2", roll_value=3) → progress=3

        Final: stack_1 ROAD progress=0, stack_2 ROAD progress=3.
        """
        player1_stacks = create_stacks_in_hell()
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[],
            current_event=CurrentEvent.PLAYER_ROLL,
        )

        # Roll 6, Roll 6, Roll 3
        r1 = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert r1.success and r1.state is not None
        assert r1.state.current_turn.rolls_to_allocate == [6]

        r2 = process_action(r1.state, RollAction(value=6), PLAYER_1_ID)
        assert r2.success and r2.state is not None
        assert r2.state.current_turn.rolls_to_allocate == [6, 6]

        r3 = process_action(r2.state, RollAction(value=3), PLAYER_1_ID)
        assert r3.success and r3.state is not None
        assert r3.state.current_turn.rolls_to_allocate == [6, 6, 3]
        assert r3.state.current_event == CurrentEvent.PLAYER_CHOICE

        # AwaitingChoice should show roll 6 (HELL exits), roll 3 excluded (no moves)
        awaiting1 = find_awaiting(r3.events)
        assert awaiting1 is not None
        assert 6 in get_rolls_offered(awaiting1)

        # Exit stack_1 with roll 6
        r4 = process_action(
            r3.state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert r4.success and r4.state is not None
        exit1 = [e for e in r4.events if isinstance(e, StackExitedHell)]
        assert len(exit1) == 1 and exit1[0].stack_id == "stack_1"

        # Remaining [6, 3]: roll 6 offers HELL exits + stack_1 advance
        assert r4.state.current_event == CurrentEvent.PLAYER_CHOICE
        awaiting2 = find_awaiting(r4.events)
        assert awaiting2 is not None
        assert "stack_2" in get_moves_for_roll(awaiting2, 6)

        # Exit stack_2 with roll 6 → merges with stack_1 at progress=0
        r5 = process_action(
            r4.state, MoveAction(stack_id="stack_2", roll_value=6), PLAYER_1_ID
        )
        assert r5.success and r5.state is not None
        exit2 = [e for e in r5.events if isinstance(e, StackExitedHell)]
        assert len(exit2) == 1 and exit2[0].stack_id == "stack_2"

        # Remaining [3]: recomputed against merged stack
        assert r5.state.current_event == CurrentEvent.PLAYER_CHOICE
        awaiting3 = find_awaiting(r5.events)
        assert awaiting3 is not None
        assert 3 in get_rolls_offered(awaiting3)
        # stack_2 (split from stack_1_2, height=1) can move 3
        assert "stack_2" in get_moves_for_roll(awaiting3, 3)

        # Move stack_2 (split from merged stack) with roll 3 → progress=3
        r6 = process_action(
            r5.state, MoveAction(stack_id="stack_2", roll_value=3), PLAYER_1_ID
        )
        assert r6.success and r6.state is not None

        moved = [e for e in r6.events if isinstance(e, StackMoved)]
        assert len(moved) == 1
        assert moved[0].stack_id == "stack_2"
        assert moved[0].to_progress == 3

        # Verify final state
        final_p1 = next(p for p in r6.state.players if p.player_id == PLAYER_1_ID)
        s1 = next(s for s in final_p1.stacks if s.stack_id == "stack_1")
        s2 = next(s for s in final_p1.stacks if s.stack_id == "stack_2")
        assert s1.state == StackState.ROAD and s1.progress == 0
        assert s2.state == StackState.ROAD and s2.progress == 3


# ---------------------------------------------------------------------------
# 8. Roll allocation after a move
# ---------------------------------------------------------------------------


class TestRollAllocationAfterMove:
    """After a move is made, remaining accumulated rolls should still be
    available for further moves."""

    def test_remaining_rolls_available_after_move(
        self, standard_board_setup: BoardSetup
    ):
        """Player has stack_1 on ROAD at progress=10. Rolls=[6, 4].

        Player moves stack_1 with roll_value=6 → progress=16.
        Remaining roll [4] should offer AwaitingChoice with recomputed moves.
        """
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell()

        state = make_two_player_game(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6, 4],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        # Move stack_1 with roll_value=6 → progress 10+6=16
        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID
        )
        assert result.success and result.state is not None

        moved = [e for e in result.events if isinstance(e, StackMoved)]
        assert len(moved) == 1
        assert moved[0].to_progress == 16

        # Remaining [4]: AwaitingChoice with recomputed moves
        assert result.state.current_event == CurrentEvent.PLAYER_CHOICE
        assert result.state.current_turn.rolls_to_allocate == [4]

        awaiting = find_awaiting(result.events)
        assert awaiting is not None
        assert 4 in get_rolls_offered(awaiting)

        # stack_1 at progress=16 can advance 4 to 20
        assert "stack_1" in get_moves_for_roll(awaiting, 4)
