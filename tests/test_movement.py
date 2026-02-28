"""Tests for stack movement on the board.

Critical scenarios tested:
- Stack moves forward on ROAD
- Stack transitions from ROAD to HOMESTRETCH
- Legal moves calculation
- Move validation

TODO (Good to have):
- [ ] Test movement with multiple roll options
- [ ] Test movement history tracking
- [ ] Test invalid move rejection details
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    StackState,
    Turn,
)
from app.services.game.engine import MoveAction, RollAction, process_action
from app.services.game.engine.events import StackMoved

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
)


class TestStackMovement:
    """Test basic stack movement."""

    def test_stack_moves_forward_on_road(self, two_player_board_setup: BoardSetup):
        """Stack should move forward by the roll value."""
        # Player 1 with stack at progress 10
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
        )

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
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 4
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move the stack
        assert "stack_1" in state.current_turn.legal_moves

        result = process_action(state, MoveAction(stack_id="stack_1"), PLAYER_1_ID)
        assert result.success

        # Verify StackMoved event
        move_event = next((e for e in result.events if e.event_type == "stack_moved"), None)
        assert move_event is not None
        assert isinstance(move_event, StackMoved)
        assert move_event.stack_id == "stack_1"
        assert move_event.from_progress == 10
        assert move_event.to_progress == 14
        assert move_event.roll_used == 4

        # Verify stack position in state
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert stack.progress == 14

    def test_stack_state_transition_road_to_homestretch(self, two_player_board_setup: BoardSetup):
        """Stack should transition from ROAD to HOMESTRETCH when crossing threshold."""
        # Player 1 with stack at progress 50 (homestretch starts at 52)
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 50),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
        )

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
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 4 (50 + 4 = 54, in homestretch)
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        state = result.state

        # Move the stack
        result = process_action(state, MoveAction(stack_id="stack_1"), PLAYER_1_ID)
        assert result.success

        # Verify stack is now in HOMESTRETCH
        move_event = next(e for e in result.events if e.event_type == "stack_moved")
        assert move_event.from_state == StackState.ROAD
        assert move_event.to_state == StackState.HOMESTRETCH

        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert stack.state == StackState.HOMESTRETCH


class TestLegalMoves:
    """Test legal move calculation."""

    def test_legal_moves_includes_all_movable_stacks(self, two_player_board_setup: BoardSetup):
        """Legal moves should include all stacks that can legally move."""
        # Player 1 with two stacks on road
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.ROAD, 1, 20),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
        )

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
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 3 (both stacks can move)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        legal_moves = result.state.current_turn.legal_moves
        assert "stack_1" in legal_moves
        assert "stack_2" in legal_moves
        # Stacks in hell cannot move with non-6
        assert "stack_3" not in legal_moves
        assert "stack_4" not in legal_moves

    def test_stacks_in_heaven_not_in_legal_moves(self, two_player_board_setup: BoardSetup):
        """Stacks in HEAVEN should not appear in legal moves."""
        # Player 1 with one stack in heaven, one on road
        player1_stacks = [
            create_stack("stack_1", StackState.HEAVEN, 1, 57),
            create_stack("stack_2", StackState.ROAD, 1, 10),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
        )

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
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 3
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        legal_moves = result.state.current_turn.legal_moves
        assert "stack_1" not in legal_moves  # In heaven
        assert "stack_2" in legal_moves  # On road


class TestMoveValidation:
    """Test move validation."""

    def test_cannot_move_illegal_stack(self, two_player_board_setup: BoardSetup):
        """Attempting to move an illegal stack should fail."""
        # Player 1 with stack on road
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
        )

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
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 3
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Try to move stack in hell (not in legal moves)
        result = process_action(state, MoveAction(stack_id="stack_2"), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "ILLEGAL_MOVE"


# TODO: Good to have tests
# class TestMultipleRollAllocation:
#     """Test allocating multiple rolls to moves."""
#
#     def test_multiple_rolls_allocated_in_order(self):
#         """Multiple accumulated rolls should be used in order."""
#         pass
#
# class TestMoveHistory:
#     """Test that moves are properly tracked."""
#
#     def test_move_events_have_correct_sequence(self):
#         """Move events should have correct seq numbers."""
#         pass
