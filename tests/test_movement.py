"""Tests for token movement on the board.

Critical scenarios tested:
- Token moves forward on ROAD
- Token transitions from ROAD to HOMESTRETCH
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
    TokenState,
    Turn,
)
from app.services.game.engine import MoveAction, RollAction, process_action
from app.services.game.engine.events import TokenMoved

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_token,
)


class TestTokenMovement:
    """Test basic token movement."""

    def test_token_moves_forward_on_road(self, two_player_board_setup: BoardSetup):
        """Token should move forward by the roll value."""
        # Player 1 with token at position 10
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
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

        # Move the token
        token_id = f"{PLAYER_1_ID}_token_1"
        assert token_id in state.current_turn.legal_moves

        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify TokenMoved event
        move_event = next((e for e in result.events if e.event_type == "token_moved"), None)
        assert move_event is not None
        assert isinstance(move_event, TokenMoved)
        assert move_event.token_id == token_id
        assert move_event.from_progress == 10
        assert move_event.to_progress == 14
        assert move_event.roll_used == 4

        # Verify token position in state
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        token = next(t for t in player1.tokens if t.token_id == token_id)
        assert token.progress == 14

    def test_token_state_transition_road_to_homestretch(self, two_player_board_setup: BoardSetup):
        """Token should transition from ROAD to HOMESTRETCH when crossing threshold."""
        # Player 1 with token at position 50 (homestretch starts at 52)
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 50),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
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

        # Move the token
        token_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify token is now in HOMESTRETCH
        move_event = next(e for e in result.events if e.event_type == "token_moved")
        assert move_event.from_state == TokenState.ROAD
        assert move_event.to_state == TokenState.HOMESTRETCH

        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        token = next(t for t in player1.tokens if t.token_id == token_id)
        assert token.state == TokenState.HOMESTRETCH


class TestLegalMoves:
    """Test legal move calculation."""

    def test_legal_moves_includes_all_movable_tokens(self, two_player_board_setup: BoardSetup):
        """Legal moves should include all tokens that can legally move."""
        # Player 1 with two tokens on road
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.ROAD, 20),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
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

        # Roll 3 (both tokens can move)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        legal_moves = result.state.current_turn.legal_moves
        assert f"{PLAYER_1_ID}_token_1" in legal_moves
        assert f"{PLAYER_1_ID}_token_2" in legal_moves
        # Tokens in hell cannot move with non-6
        assert f"{PLAYER_1_ID}_token_3" not in legal_moves
        assert f"{PLAYER_1_ID}_token_4" not in legal_moves

    def test_tokens_in_heaven_not_in_legal_moves(self, two_player_board_setup: BoardSetup):
        """Tokens in HEAVEN should not appear in legal moves."""
        # Player 1 with one token in heaven, one on road
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.HEAVEN, 57),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.ROAD, 10),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
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
        assert f"{PLAYER_1_ID}_token_1" not in legal_moves  # In heaven
        assert f"{PLAYER_1_ID}_token_2" in legal_moves  # On road


class TestMoveValidation:
    """Test move validation."""

    def test_cannot_move_illegal_token(self, two_player_board_setup: BoardSetup):
        """Attempting to move an illegal token should fail."""
        # Player 1 with token on road
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
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

        # Try to move token in hell (not in legal moves)
        illegal_token_id = f"{PLAYER_1_ID}_token_2"
        result = process_action(state, MoveAction(token_or_stack_id=illegal_token_id), PLAYER_1_ID)

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
