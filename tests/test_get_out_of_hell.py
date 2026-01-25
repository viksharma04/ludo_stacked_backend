"""Tests for getting out of hell (token exiting start area).

Critical scenarios tested:
- Token exits HELL with a 6
- Token exits HELL and lands on correct position
- Multiple get-out rolls configuration support

TODO (Good to have):
- [ ] Test get-out when starting position is occupied by own token (stacking)
- [ ] Test get-out when starting position is occupied by opponent (capture)
- [ ] Test get-out on safe space behavior
- [ ] Test multiple tokens getting out in same turn
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Player,
    TokenState,
    Turn,
)
from app.services.game.engine import MoveAction, RollAction, process_action
from app.services.game.engine.events import AwaitingChoice, TokenExitedHell

from .conftest import (
    PLAYER_1_ID,
)


class TestGetOutOfHell:
    """Test tokens exiting HELL state."""

    def test_roll_six_allows_token_to_exit_hell(self, game_player1_turn: GameState):
        """Rolling a 6 should allow player to move a token out of HELL."""
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

        # Should have legal moves for tokens in hell (using the 6)
        assert len(awaiting.legal_moves) > 0

    def test_token_exits_hell_to_road_position_zero(self, game_player1_turn: GameState):
        """Token exiting HELL should land on ROAD at progress 0."""
        state = game_player1_turn

        # Roll a 6, then non-6
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        state = result.state
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Choose a token from hell
        token_id = f"{PLAYER_1_ID}_token_1"
        assert token_id in state.current_turn.legal_moves

        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify TokenExitedHell event
        exit_event = next((e for e in result.events if e.event_type == "token_exited_hell"), None)
        assert exit_event is not None
        assert isinstance(exit_event, TokenExitedHell)
        assert exit_event.token_id == token_id
        assert exit_event.roll_used == 6

        # Verify token state in new game state
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        moved_token = next(t for t in player1.tokens if t.token_id == token_id)

        assert moved_token.state == TokenState.ROAD
        assert moved_token.progress == 0

    def test_non_six_roll_cannot_exit_hell(self, game_player1_turn: GameState):
        """Rolling a non-6 with all tokens in HELL should have no legal moves."""
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
    """Test multiple tokens getting out in the same turn."""

    def test_multiple_sixes_can_get_multiple_tokens_out(self, game_player1_turn: GameState):
        """Rolling multiple 6s should allow getting multiple tokens out."""
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

        # Get first token out
        token1_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token1_id), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should still be player 1's turn with more rolls to allocate
        # (second 6 should allow getting another token out)
        if state.current_event == CurrentEvent.PLAYER_CHOICE:
            token2_id = f"{PLAYER_1_ID}_token_2"
            if token2_id in state.current_turn.legal_moves:
                result = process_action(state, MoveAction(token_or_stack_id=token2_id), PLAYER_1_ID)
                assert result.success

                # Verify second token is now on road
                new_state = result.state
                player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
                token2 = next(t for t in player1.tokens if t.token_id == token2_id)
                assert token2.state == TokenState.ROAD


# TODO: Good to have tests
# class TestGetOutWithCollision:
#     """Test getting out when starting position has another piece."""
#
#     def test_get_out_stacks_with_own_token_on_start(self):
#         """Getting out when own token is on starting position should stack."""
#         pass
#
#     def test_get_out_captures_opponent_on_start(self):
#         """Getting out when opponent is on starting position should capture."""
#         pass
#
# class TestGetOutOnSafeSpace:
#     """Test get-out behavior when starting position is a safe space."""
#     pass
