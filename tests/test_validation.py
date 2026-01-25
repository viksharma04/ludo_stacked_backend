"""Tests for action validation.

Critical scenarios tested:
- Game phase validation (NOT_STARTED, IN_PROGRESS, FINISHED)
- Turn validation (not your turn)
- Action type validation (roll vs move)
- StartGame action validation

TODO (Good to have):
- [ ] Test validation error codes and messages
- [ ] Test concurrent action rejection
- [ ] Test replay protection
"""

from app.schemas.game_engine import (
    CurrentEvent,
    GamePhase,
    GameState,
)
from app.services.game.engine import (
    MoveAction,
    RollAction,
    StartGameAction,
    process_action,
)

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
)


class TestGamePhaseValidation:
    """Test validation based on game phase."""

    def test_cannot_roll_before_game_starts(self, two_player_game_not_started: GameState):
        """Rolling before game starts should fail."""
        result = process_action(two_player_game_not_started, RollAction(value=6), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "GAME_NOT_STARTED"

    def test_cannot_move_before_game_starts(self, two_player_game_not_started: GameState):
        """Moving before game starts should fail."""
        result = process_action(
            two_player_game_not_started,
            MoveAction(token_or_stack_id=f"{PLAYER_1_ID}_token_1"),
            PLAYER_1_ID,
        )

        assert not result.success
        assert result.error_code == "GAME_NOT_STARTED"

    def test_cannot_start_game_twice(self, two_player_game_not_started: GameState):
        """Starting an already started game should fail."""
        # Start the game first
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)
        assert result.success
        started_state = result.state

        # Try to start again
        result = process_action(started_state, StartGameAction(), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "GAME_ALREADY_STARTED"

    def test_cannot_act_in_finished_game(self, two_player_board_setup):
        """Actions in finished game should fail."""
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
        )

        # Create a finished game
        state = GameState(
            phase=GamePhase.FINISHED,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=two_player_board_setup,
            current_turn=None,
        )

        result = process_action(state, RollAction(value=6), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "GAME_FINISHED"


class TestTurnValidation:
    """Test validation based on turn ownership."""

    def test_cannot_roll_on_other_players_turn(self, game_player1_turn: GameState):
        """Player 2 cannot roll on Player 1's turn."""
        result = process_action(game_player1_turn, RollAction(value=6), PLAYER_2_ID)

        assert not result.success
        assert result.error_code == "NOT_YOUR_TURN"

    def test_cannot_move_on_other_players_turn(self, game_with_token_on_road: GameState):
        """Player 2 cannot move on Player 1's turn."""
        # First roll to get to choice state
        result = process_action(game_with_token_on_road, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Player 2 tries to move
        result = process_action(
            state,
            MoveAction(token_or_stack_id=f"{PLAYER_1_ID}_token_1"),
            PLAYER_2_ID,
        )

        assert not result.success
        assert result.error_code == "NOT_YOUR_TURN"


class TestActionTypeValidation:
    """Test validation based on expected action type."""

    def test_cannot_move_when_roll_expected(self, game_player1_turn: GameState):
        """Cannot move when game is waiting for roll."""
        result = process_action(
            game_player1_turn,
            MoveAction(token_or_stack_id=f"{PLAYER_1_ID}_token_1"),
            PLAYER_1_ID,
        )

        assert not result.success
        assert result.error_code == "INVALID_ACTION"

    def test_cannot_roll_when_move_expected(self, game_with_token_on_road: GameState):
        """Cannot roll when game is waiting for move choice."""
        # First roll to get to choice state
        result = process_action(game_with_token_on_road, RollAction(value=3), PLAYER_1_ID)
        state = result.state
        assert state.current_event == CurrentEvent.PLAYER_CHOICE

        # Try to roll again
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "INVALID_ACTION"


class TestStartGameAction:
    """Test StartGameAction validation and processing."""

    def test_start_game_creates_first_turn(self, two_player_game_not_started: GameState):
        """Starting game should create the first turn."""
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)

        assert result.success
        assert result.state.phase == GamePhase.IN_PROGRESS
        assert result.state.current_turn is not None
        assert result.state.current_turn.player_id == PLAYER_1_ID
        assert result.state.current_turn.current_turn_order == 1

    def test_start_game_emits_game_started_event(self, two_player_game_not_started: GameState):
        """Starting game should emit GameStarted event."""
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)

        assert result.success

        # Find game started event
        game_started = next((e for e in result.events if e.event_type == "game_started"), None)
        assert game_started is not None
        assert len(game_started.player_order) == 2
        assert game_started.first_player_id == PLAYER_1_ID


class TestIllegalMoveValidation:
    """Test validation of illegal moves."""

    def test_cannot_move_token_not_in_legal_moves(self, game_with_token_on_road: GameState):
        """Cannot move a token that's not in legal moves."""
        # Roll to get to choice state
        result = process_action(game_with_token_on_road, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Try to move a token in hell (not a legal move with roll of 3)
        illegal_token = f"{PLAYER_1_ID}_token_2"  # In hell
        result = process_action(state, MoveAction(token_or_stack_id=illegal_token), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "ILLEGAL_MOVE"

    def test_cannot_move_nonexistent_token(self, game_with_token_on_road: GameState):
        """Cannot move a token that doesn't exist."""
        # Roll to get to choice state
        result = process_action(game_with_token_on_road, RollAction(value=3), PLAYER_1_ID)
        state = result.state

        # Try to move a nonexistent token
        result = process_action(state, MoveAction(token_or_stack_id="fake_token"), PLAYER_1_ID)

        assert not result.success
        assert result.error_code == "ILLEGAL_MOVE"


# TODO: Good to have tests
# class TestValidationErrorMessages:
#     """Test that validation errors have helpful messages."""
#
#     def test_error_messages_are_descriptive(self):
#         """Error messages should explain what went wrong."""
#         pass
#
# class TestReplayProtection:
#     """Test that duplicate/replayed actions are rejected."""
#
#     def test_same_action_cannot_be_processed_twice(self):
#         """Processing the exact same action twice should fail."""
#         pass
