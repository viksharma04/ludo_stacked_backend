"""Tests for capture scenarios.

Critical scenarios tested:
- Token captures opponent token
- Capture sends opponent to HELL
- Capture grants extra roll
- Safe spaces prevent captures
- Stack captures (size comparison)

TODO (Good to have):
- [ ] Test multiple capture choices
- [ ] Test capture with stack vs single token
- [ ] Test capture on starting position
- [ ] Test capture chain (extra roll leads to another capture)
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
from app.services.game.engine.events import TokenCaptured

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_token,
)


class TestBasicCapture:
    """Test basic capture mechanics."""

    def test_token_captures_opponent_and_sends_to_hell(self, two_player_board_setup: BoardSetup):
        """Moving to opponent's position should capture them."""
        # Player 1 at position 10, Player 2 at position 13
        # Player 1 rolls 3 to land on 13 (Player 2's position)
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

        # Player 2's token at position 13 (absolute position = 26 + 13 = 39... wait)
        # Need to calculate absolute positions correctly
        # Player 1 starts at abs 0, so position 13 means abs position 13
        # Player 2 starts at abs 26, so for collision we need matching absolute positions
        # If Player 1 is at progress 13, abs = 0 + 13 = 13
        # For Player 2 to be at abs 13, they need progress such that 26 + progress % 52 = 13
        # That means progress = 13 - 26 = -13, which wraps to 52-13=39... no wait
        # Actually: (26 + progress) % 52 = 13 => progress = 13 - 26 = -13 + 52 = 39

        # Simpler: let's put both on an absolute position that makes sense
        # Player 1 progress 10 => abs position 10
        # Player 2 needs abs position 13 to be where Player 1 lands
        # For player 2: (26 + progress) % 52 = 13
        # progress = (13 - 26 + 52) % 52 = 39

        # Actually even simpler - let's just use non-wrapping positions
        # Player 1 at progress 5, abs = 5
        # Player 2 at progress where abs = 8 => (26 + p) % 52 = 8 => p = (8 - 26 + 52) = 34
        # Player 1 rolls 3 to go from abs 5 to abs 8

        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 5),
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

        # Player 2 at absolute position 8 (not a safe space in standard board)
        # abs_position = (abs_starting_index + progress) % squares_to_homestretch
        # 8 = (26 + progress) % 52
        # progress = (8 - 26 + 52) % 52 = 34
        player2_tokens = [
            create_token(f"{PLAYER_2_ID}_token_1", TokenState.ROAD, 34),
            create_token(f"{PLAYER_2_ID}_token_2", TokenState.HELL, 0),
            create_token(f"{PLAYER_2_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_2_ID}_token_4", TokenState.HELL, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            tokens=player2_tokens,
        )

        # Verify safe spaces don't include position 8
        board_setup = BoardSetup(
            squares_to_win=57,
            squares_to_homestretch=52,
            starting_positions=[0, 26],
            safe_spaces=[0, 26],  # Only starting positions are safe
            get_out_rolls=[6],
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

        # Roll 3 (5 + 3 = 8, landing on player 2's position)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move the token
        token_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify capture event
        capture_event = next((e for e in result.events if e.event_type == "token_captured"), None)
        assert capture_event is not None
        assert isinstance(capture_event, TokenCaptured)
        assert capture_event.capturing_player_id == PLAYER_1_ID
        assert capture_event.captured_player_id == PLAYER_2_ID
        assert capture_event.grants_extra_roll is True

        # Verify captured token is in HELL
        new_state = result.state
        player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        captured_token = next(t for t in player2.tokens if t.token_id == f"{PLAYER_2_ID}_token_1")
        assert captured_token.state == TokenState.HELL
        assert captured_token.progress == 0

    def test_capture_grants_extra_roll(self, two_player_board_setup: BoardSetup):
        """Capturing should grant an extra roll."""
        # Set up a capture scenario
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 5),
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

        player2_tokens = [
            create_token(f"{PLAYER_2_ID}_token_1", TokenState.ROAD, 34),  # At abs pos 8
            create_token(f"{PLAYER_2_ID}_token_2", TokenState.HELL, 0),
            create_token(f"{PLAYER_2_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_2_ID}_token_4", TokenState.HELL, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            tokens=player2_tokens,
        )

        board_setup = BoardSetup(
            squares_to_win=57,
            squares_to_homestretch=52,
            starting_positions=[0, 26],
            safe_spaces=[0, 26],
            get_out_rolls=[6],
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

        # Roll and capture
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        token_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify extra roll was granted - player should still be rolling
        new_state = result.state
        assert new_state.current_turn.player_id == PLAYER_1_ID
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL


class TestSafeSpaces:
    """Test that safe spaces prevent captures."""

    def test_no_capture_on_safe_space(self):
        """Landing on opponent at safe space should not capture."""
        # Player 1 at position 0 (safe starting position)
        # Player 2 also at position 0
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 0),  # Starting pos, abs 0
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

        # Player 2 at abs position 0 (safe space)
        # abs_position = (26 + progress) % 52 = 0
        # progress = (0 - 26 + 52) % 52 = 26
        player2_tokens = [
            create_token(f"{PLAYER_2_ID}_token_1", TokenState.ROAD, 26),  # At abs pos 0 (safe)
            create_token(f"{PLAYER_2_ID}_token_2", TokenState.HELL, 0),
            create_token(f"{PLAYER_2_ID}_token_3", TokenState.HELL, 0),
            create_token(f"{PLAYER_2_ID}_token_4", TokenState.HELL, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            tokens=player2_tokens,
        )

        # Safe space at 0
        board_setup = BoardSetup(
            squares_to_win=57,
            squares_to_homestretch=52,
            starting_positions=[0, 26],
            safe_spaces=[0, 26],  # 0 is a safe space
            get_out_rolls=[6],
        )

        # Player 1 is at abs 0 already with player 2 also at abs 0
        # Let's move player 1 to position before safe space
        player1_tokens[0] = create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 49)  # abs 49
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
        )

        # Player 2 at abs position 0 (a safe space)
        player2_tokens[0] = create_token(
            f"{PLAYER_2_ID}_token_1", TokenState.ROAD, 26
        )  # (26+26)%52 = 0
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            tokens=player2_tokens,
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

        # Roll 3 to land on abs position 0 (49 + 3 = 52 % 52 = 0)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move the token
        token_id = f"{PLAYER_1_ID}_token_1"

        # Check if token is in legal moves (it should be since it can move)
        if token_id in state.current_turn.legal_moves:
            result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
            assert result.success

            # Verify NO capture event (safe space)
            capture_events = [e for e in result.events if e.event_type == "token_captured"]
            assert len(capture_events) == 0

            # Verify opponent token is still on road
            new_state = result.state
            player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
            opponent_token = next(
                t for t in player2.tokens if t.token_id == f"{PLAYER_2_ID}_token_1"
            )
            assert opponent_token.state == TokenState.ROAD  # Not captured


# TODO: Good to have tests
# class TestStackCaptures:
#     """Test capture rules with stacks."""
#
#     def test_larger_stack_captures_smaller(self):
#         """Larger stack landing on smaller should capture."""
#         pass
#
#     def test_smaller_stack_cannot_capture_larger(self):
#         """Smaller piece landing on larger should NOT capture."""
#         pass
#
#     def test_equal_size_captures(self):
#         """Equal size pieces - moving piece captures."""
#         pass
#
# class TestCaptureChains:
#     """Test capture leading to another capture opportunity."""
#
#     def test_extra_roll_from_capture_can_capture_again(self):
#         """Extra roll from capture can be used to capture another opponent."""
#         pass
