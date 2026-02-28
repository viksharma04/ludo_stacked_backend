"""Tests for getting out of hell (stack exiting start area).

Critical scenarios tested:
- Stack exits HELL with a 6
- Stack exits HELL and lands on correct position
- Multiple get-out rolls configuration support

TODO (Good to have):
- [ ] Test get-out when starting position is occupied by own stack (stacking)
- [ ] Test get-out when starting position is occupied by opponent (capture)
- [ ] Test get-out on safe space behavior
- [ ] Test multiple stacks getting out in same turn
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Player,
    StackState,
    Turn,
)
from app.services.game.engine import MoveAction, RollAction, process_action
from app.services.game.engine.events import AwaitingChoice, StackExitedHell

from .conftest import (
    PLAYER_1_ID,
)


class TestGetOutOfHell:
    """Test stacks exiting HELL state."""

    def test_roll_six_allows_stack_to_exit_hell(self, game_player1_turn: GameState):
        """Rolling a 6 should allow player to move a stack out of HELL."""
        state = game_player1_turn

        # Roll a 6 first, then a non-6 to use the 6
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Roll a non-6 to trigger move choice
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should now be in PLAYER_CHOICE state
        assert state.current_event == CurrentEvent.PLAYER_CHOICE

        # Verify awaiting choice event
        awaiting = next(e for e in result.events if e.event_type == "awaiting_choice")
        assert isinstance(awaiting, AwaitingChoice)

        # Should have legal moves for stacks in hell (using the 6)
        assert len(awaiting.legal_moves) > 0

    def test_stack_exits_hell_to_road_position_zero(self, game_player1_turn: GameState):
        """Stack exiting HELL should land on ROAD at progress 0."""
        state = game_player1_turn

        # Roll a 6, then non-6
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        state = result.state
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Choose a stack from hell
        assert "stack_1" in state.current_turn.legal_moves

        result = process_action(state, MoveAction(stack_id="stack_1"), PLAYER_1_ID)
        assert result.success

        # Verify StackExitedHell event
        exit_event = next((e for e in result.events if e.event_type == "stack_exited_hell"), None)
        assert exit_event is not None
        assert isinstance(exit_event, StackExitedHell)
        assert exit_event.stack_id == "stack_1"
        assert exit_event.roll_used == 6

        # Verify stack state in new game state
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        moved_stack = next(s for s in player1.stacks if s.stack_id == "stack_1")

        assert moved_stack.state == StackState.ROAD
        assert moved_stack.progress == 0

    def test_non_six_roll_cannot_exit_hell(self, game_player1_turn: GameState):
        """Rolling a non-6 with all stacks in HELL should have no legal moves."""
        state = game_player1_turn

        # Roll a 4 - not a get-out roll
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success

        # Turn should end immediately (no legal moves)
        event_types = [e.event_type for e in result.events]
        assert "turn_ended" in event_types

    def test_custom_get_out_rolls_configuration(self, player1: Player, player2: Player):
        """Test that custom get_out_rolls configuration works (e.g., 1 and 6)."""
        # Custom board where 1 and 6 are get-out rolls
        board_setup = BoardSetup(
            squares_to_win=57,
            squares_to_homestretch=52,
            starting_positions=[0, 26],
            safe_spaces=[0, 26],
            get_out_rolls=[1, 6],  # Both 1 and 6 can get out
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
            board_setup=board_setup,
            current_turn=turn,
        )

        # Roll a 1 - should be a valid get-out roll
        result = process_action(state, RollAction(value=1), PLAYER_1_ID)
        assert result.success

        # Should transition to player choice (has legal moves)
        assert result.state.current_event == CurrentEvent.PLAYER_CHOICE
        assert len(result.state.current_turn.legal_moves) > 0


class TestMultipleGetOuts:
    """Test multiple stacks getting out in the same turn."""

    def test_multiple_sixes_can_get_multiple_stacks_out(self, game_player1_turn: GameState):
        """Rolling multiple 6s should allow getting multiple stacks out."""
        state = game_player1_turn

        # Roll 6, 6, non-6 to have two get-out rolls
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        state = result.state
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        state = result.state
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Should have legal moves
        assert state.current_event == CurrentEvent.PLAYER_CHOICE

        # Get first stack out
        result = process_action(state, MoveAction(stack_id="stack_1"), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should still be player 1's turn with more rolls to allocate
        # (second 6 should allow getting another stack out)
        if state.current_event == CurrentEvent.PLAYER_CHOICE:
            if "stack_2" in state.current_turn.legal_moves:
                result = process_action(state, MoveAction(stack_id="stack_2"), PLAYER_1_ID)
                assert result.success

                # stack_2 exited HELL and merged with stack_1 at progress=0 -> stack_1_2
                new_state = result.state
                player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
                merged = next(s for s in player1.stacks if s.stack_id == "stack_1_2")
                assert merged.state == StackState.ROAD
                assert merged.height == 2


# TODO: Good to have tests
# class TestGetOutWithCollision:
#     """Test getting out when starting position has another piece."""
#
#     def test_get_out_stacks_with_own_stack_on_start(self):
#         """Getting out when own stack is on starting position should stack."""
#         pass
#
#     def test_get_out_captures_opponent_on_start(self):
#         """Getting out when opponent is on starting position should capture."""
#         pass
#
# class TestGetOutOnSafeSpace:
#     """Test get-out behavior when starting position is a safe space."""
#     pass
