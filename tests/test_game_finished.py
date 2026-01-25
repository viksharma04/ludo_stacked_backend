"""Tests for game winning and finishing scenarios.

Critical scenarios tested:
- Single token reaches heaven
- All tokens reach heaven (game finished)
- Exact roll required to reach heaven
- Cannot overshoot heaven

TODO (Good to have):
- [ ] Test GameEnded event with final rankings
- [ ] Test multi-player finish order tracking
- [ ] Test game continues after one player finishes (multiplayer)
- [ ] Test stack reaching heaven
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
from app.services.game.engine.events import TokenReachedHeaven

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_token,
)


class TestTokenReachingHeaven:
    """Test tokens reaching the HEAVEN state (finished)."""

    def test_token_reaches_heaven_with_exact_roll(self, two_player_board_setup: BoardSetup):
        """Token should reach HEAVEN with exact roll to squares_to_win."""
        # Player 1 with token at position 55 (needs exactly 2 to win at 57)
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.HOMESTRETCH, 55),
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

        # Roll exactly 2
        result = process_action(state, RollAction(value=2), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should have legal move
        assert state.current_event == CurrentEvent.PLAYER_CHOICE
        token_id = f"{PLAYER_1_ID}_token_1"
        assert token_id in state.current_turn.legal_moves

        # Make the move
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify TokenReachedHeaven event
        heaven_event = next(
            (e for e in result.events if e.event_type == "token_reached_heaven"), None
        )
        assert heaven_event is not None
        assert isinstance(heaven_event, TokenReachedHeaven)
        assert heaven_event.token_id == token_id

        # Verify token state
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        token = next(t for t in player1.tokens if t.token_id == token_id)
        assert token.state == TokenState.HEAVEN
        assert token.progress == 57  # squares_to_win

    def test_cannot_overshoot_heaven(self, two_player_board_setup: BoardSetup):
        """Token cannot move if roll would exceed squares_to_win."""
        # Player 1 with token at position 55 (needs exactly 2 to win at 57)
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.HOMESTRETCH, 55),
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

        # Roll a 5 (would overshoot 57)
        result = process_action(state, RollAction(value=5), PLAYER_1_ID)
        assert result.success

        # Turn should end - no legal moves
        event_types = [e.event_type for e in result.events]
        assert "turn_ended" in event_types

    def test_token_in_homestretch_state(self, two_player_board_setup: BoardSetup):
        """Token should transition to HOMESTRETCH state when entering final stretch."""
        # Player 1 with token at position 50 (enters homestretch at 52)
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

        # Roll 3 (50 + 3 = 53, enters homestretch at 52)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Make the move
        token_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify token is now in HOMESTRETCH
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        token = next(t for t in player1.tokens if t.token_id == token_id)
        assert token.state == TokenState.HOMESTRETCH
        assert token.progress == 53


class TestAllTokensInHeaven:
    """Test scenarios where all tokens reach heaven."""

    def test_last_token_reaching_heaven(self, two_player_board_setup: BoardSetup):
        """When last token reaches heaven, appropriate events should fire."""
        # Player 1 with 3 tokens in heaven, 1 about to finish
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.HOMESTRETCH, 55),  # Needs 2
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.HEAVEN, 57),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.HEAVEN, 57),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HEAVEN, 57),
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

        # Roll 2 and move last token
        result = process_action(state, RollAction(value=2), PLAYER_1_ID)
        state = result.state

        token_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify TokenReachedHeaven event
        heaven_event = next(
            (e for e in result.events if e.event_type == "token_reached_heaven"), None
        )
        assert heaven_event is not None

        # Verify all tokens are in heaven
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        assert all(t.state == TokenState.HEAVEN for t in player1.tokens)


# TODO: Good to have tests
# class TestGameEndedEvent:
#     """Test GameEnded event and final rankings."""
#
#     def test_game_ended_event_has_winner(self):
#         """GameEnded event should include winner_id."""
#         pass
#
#     def test_game_ended_event_has_rankings(self):
#         """GameEnded event should include final_rankings in finish order."""
#         pass
#
# class TestMultiplayerFinish:
#     """Test game continuation after one player finishes."""
#
#     def test_game_continues_after_one_player_wins(self):
#         """Game should continue for remaining players after one wins."""
#         pass
#
# class TestStackReachingHeaven:
#     """Test stacks reaching heaven."""
#
#     def test_stack_reaching_heaven_finishes_all_tokens(self):
#         """All tokens in a stack should finish when stack reaches heaven."""
#         pass
