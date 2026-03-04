"""Tests for HELL exit collision scenarios.

When a stack exits HELL (with a 6), it lands at ROAD progress=0
(the player's starting position). Starting positions are safe spaces,
so no captures can happen there. Only height=1 stacks exist in HELL
since captured stacks are always decomposed.

Scenarios tested:
- Exit to empty starting position
- Exit merging with own stack at starting position
- Exit coexisting with opponent at starting position (safe space)
- Multiple exits in the same turn
- StackExitedHell event correctness
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Stack,
    StackState,
    Turn,
)
from app.services.game.engine.actions import MoveAction, RollAction
from app.services.game.engine.events import (
    DiceRolled,
    RollGranted,
    StackExitedHell,
    StackUpdate,
)
from app.services.game.engine.process import process_action
from tests.conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
    create_stacks_in_hell,
)


def make_game_state(
    player1_stacks: list[Stack],
    player2_stacks: list[Stack],
    board_setup: BoardSetup,
    rolls: list[int] | None = None,
    legal_moves: list[str] | None = None,
    current_event: CurrentEvent = CurrentEvent.PLAYER_CHOICE,
) -> GameState:
    """Build a game state with player 1's turn ready for a move or roll."""
    player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0, stacks=player1_stacks)
    player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26, stacks=player2_stacks)
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=False,
        rolls_to_allocate=rolls or [6],
        legal_moves=legal_moves or [],
        current_turn_order=1,
        extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=current_event,
        board_setup=board_setup,
        current_turn=turn,
    )


class TestExitToEmptyStart:
    """Test exiting HELL when the starting position is empty."""

    def test_exit_hell_to_empty_starting_position(self, standard_board_setup: BoardSetup):
        """Player 1 has all stacks in HELL. Exit stack_1 with a 6.

        After the move, stack_1 should be on ROAD at progress=0 and
        a StackExitedHell event should be emitted.
        """
        player1_stacks = create_stacks_in_hell(4)
        player2_stacks = create_stacks_in_hell(4)
        legal_moves = ["stack_1", "stack_2", "stack_3", "stack_4"]

        state = make_game_state(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            legal_moves=legal_moves,
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID)
        assert result.success

        # Verify stack_1 is now on ROAD at progress=0
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack_1 = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert stack_1.state == StackState.ROAD
        assert stack_1.progress == 0

        # Verify StackExitedHell event was emitted
        exit_events = [e for e in result.events if isinstance(e, StackExitedHell)]
        assert len(exit_events) == 1
        assert exit_events[0].stack_id == "stack_1"
        assert exit_events[0].player_id == PLAYER_1_ID


class TestExitWithOwnStackAtStart:
    """Test exiting HELL when own stack occupies the starting position."""

    def test_exit_merges_with_own_stack_at_starting_position(
        self, standard_board_setup: BoardSetup
    ):
        """Player 1 has stack_1 at ROAD progress=0 and stack_2 in HELL.

        Exiting stack_2 should land at progress=0, collide with stack_1,
        and merge into stack_1_2 (height=2).
        """
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 0),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell(4)

        state = make_game_state(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            legal_moves=["stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_2", roll_value=6), PLAYER_1_ID)
        assert result.success

        # After merge, stack_1 and stack_2 should combine into stack_1_2
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack_ids = [s.stack_id for s in player1.stacks]

        # The merged stack should exist
        assert "stack_1_2" in stack_ids
        # The individual stacks should no longer exist
        assert "stack_1" not in stack_ids
        assert "stack_2" not in stack_ids

        # Verify merged stack properties
        merged = next(s for s in player1.stacks if s.stack_id == "stack_1_2")
        assert merged.height == 2
        assert merged.state == StackState.ROAD
        assert merged.progress == 0

        # Verify events: StackExitedHell and StackUpdate (merge)
        exit_events = [e for e in result.events if isinstance(e, StackExitedHell)]
        assert len(exit_events) == 1
        assert exit_events[0].stack_id == "stack_2"

        update_events = [e for e in result.events if isinstance(e, StackUpdate)]
        assert len(update_events) == 1
        # The merged stack should be in add_stacks
        added_ids = [s.stack_id for s in update_events[0].add_stacks]
        assert "stack_1_2" in added_ids

    def test_exit_merges_with_multi_height_own_stack(self, standard_board_setup: BoardSetup):
        """Player 1 has stack_1_2 (height=2) at ROAD progress=0 and stack_3 in HELL.

        Exiting stack_3 should merge into stack_1_2_3 (height=3).
        """
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = create_stacks_in_hell(4)

        state = make_game_state(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            legal_moves=["stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_3", roll_value=6), PLAYER_1_ID)
        assert result.success

        # After merge, stack_1_2 and stack_3 should combine into stack_1_2_3
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack_ids = [s.stack_id for s in player1.stacks]

        assert "stack_1_2_3" in stack_ids
        assert "stack_1_2" not in stack_ids
        assert "stack_3" not in stack_ids

        # Verify merged stack properties
        merged = next(s for s in player1.stacks if s.stack_id == "stack_1_2_3")
        assert merged.height == 3
        assert merged.state == StackState.ROAD
        assert merged.progress == 0


class TestExitWithOpponentAtStart:
    """Test exiting HELL when opponent stack occupies the starting position.

    Starting positions are safe spaces, so no capture should occur.
    Both stacks should coexist at the same absolute position.
    """

    def test_exit_no_capture_at_safe_starting_position(self, standard_board_setup: BoardSetup):
        """Player 1 exits HELL. Player 2 has a stack at absolute position 0.

        Player 2 has abs_starting_index=26, so progress=24 maps to
        absolute position (26 + 24) % 50 = 0. Position 0 is a safe space.
        No capture should occur; both stacks coexist.
        """
        player1_stacks = [
            create_stack("stack_1", StackState.HELL, 1, 0),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        # Player 2 stack at absolute position 0: (26 + 24) % 50 = 0
        player2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 24),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_game_state(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID)
        assert result.success

        new_state = result.state

        # Verify player 1's stack is on ROAD at progress=0
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        p1_stack = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert p1_stack.state == StackState.ROAD
        assert p1_stack.progress == 0

        # Verify player 2's stack is NOT captured (still on ROAD)
        player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        p2_stack = next(s for s in player2.stacks if s.stack_id == "stack_1")
        assert p2_stack.state == StackState.ROAD
        assert p2_stack.progress == 24  # unchanged

        # No capture events should be emitted
        from app.services.game.engine.events import StackCaptured

        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 0


class TestMultipleExitsInTurn:
    """Test multiple stacks exiting HELL in the same turn via multiple 6s."""

    def test_multiple_stacks_exit_in_same_turn(self, standard_board_setup: BoardSetup):
        """Simulate rolling [6, 6, 3] and exiting two stacks from HELL.

        Integration test through process_action:
        1. RollAction(value=6) -> rolls=[6], grants extra roll
        2. RollAction(value=6) -> rolls=[6,6], grants extra roll
        3. RollAction(value=3) -> rolls=[6,6,3], calculate legal moves for first 6
        4. MoveAction for first stack -> exits HELL
        5. MoveAction for second stack -> exits HELL (using second 6)
        """
        player1_stacks = create_stacks_in_hell(4)
        player2_stacks = create_stacks_in_hell(4)

        player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0, stacks=player1_stacks)
        player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26, stacks=player2_stacks)

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

        # Step 1: Roll a 6 -> grants extra roll
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        state = result.state
        assert state.current_event == CurrentEvent.PLAYER_ROLL
        # Should have DiceRolled and RollGranted events
        dice_events = [e for e in result.events if isinstance(e, DiceRolled)]
        assert len(dice_events) == 1
        assert dice_events[0].value == 6
        assert dice_events[0].grants_extra_roll is True
        roll_granted = [e for e in result.events if isinstance(e, RollGranted)]
        assert len(roll_granted) == 1
        assert roll_granted[0].reason == "rolled_six"

        # Step 2: Roll another 6 -> grants extra roll
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        state = result.state
        assert state.current_event == CurrentEvent.PLAYER_ROLL

        # Step 3: Roll a 3 -> no extra roll, should calculate legal moves
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state
        # Should now be awaiting player choice (legal moves for the first 6)
        assert state.current_event == CurrentEvent.PLAYER_CHOICE
        assert state.current_turn.rolls_to_allocate == [6, 6, 3]
        # All 4 stacks in HELL should be legal moves (using first roll=6)
        assert len(state.current_turn.legal_moves) == 4

        # Step 4: Exit first stack from HELL
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=6), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Verify stack_1 exited
        player1 = next(p for p in state.players if p.player_id == PLAYER_1_ID)
        stack_1 = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert stack_1.state == StackState.ROAD
        assert stack_1.progress == 0

        # Should still have more rolls to allocate (second 6)
        # and should be in PLAYER_CHOICE for the next move
        assert state.current_event == CurrentEvent.PLAYER_CHOICE

        # Step 5: Exit second stack from HELL
        assert "stack_2" in state.current_turn.legal_moves
        result = process_action(state, MoveAction(stack_id="stack_2", roll_value=6), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Verify stack_2 exited and merged with stack_1 at progress=0
        player1 = next(p for p in state.players if p.player_id == PLAYER_1_ID)
        stack_ids = [s.stack_id for s in player1.stacks]
        assert "stack_1_2" in stack_ids
        merged = next(s for s in player1.stacks if s.stack_id == "stack_1_2")
        assert merged.state == StackState.ROAD
        assert merged.progress == 0
        assert merged.height == 2


class TestExitEvents:
    """Test that StackExitedHell events contain correct data."""

    def test_exit_emits_stack_exited_hell_event(self, standard_board_setup: BoardSetup):
        """StackExitedHell event should have correct player_id, stack_id,
        and roll_used=6.
        """
        player1_stacks = create_stacks_in_hell(4)
        player2_stacks = create_stacks_in_hell(4)

        state = make_game_state(
            player1_stacks=player1_stacks,
            player2_stacks=player2_stacks,
            board_setup=standard_board_setup,
            rolls=[6],
            legal_moves=["stack_1", "stack_2", "stack_3", "stack_4"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_3", roll_value=6), PLAYER_1_ID)
        assert result.success

        # Find the StackExitedHell event
        exit_events = [e for e in result.events if isinstance(e, StackExitedHell)]
        assert len(exit_events) == 1

        event = exit_events[0]
        assert event.player_id == PLAYER_1_ID
        assert event.stack_id == "stack_3"
        assert event.roll_used == 6
        assert event.event_type == "stack_exited_hell"
