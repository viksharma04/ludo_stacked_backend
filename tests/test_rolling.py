"""Tests for the dice rolling logic and turn transitions.

Critical scenarios tested:
- Three consecutive sixes penalty (turn ends)
- Rolling a 6 grants extra roll
- No legal moves causes turn to end
- Turn transitions to next player correctly

TODO (Good to have):
- [ ] Test roll accumulation (multiple rolls before choosing)
- [ ] Test initial_roll flag behavior
- [ ] Test roll value boundaries (1-6 only)
- [ ] Test roll history tracking
"""

from app.schemas.game_engine import (
    CurrentEvent,
    GamePhase,
    GameState,
    TokenState,
    Turn,
)
from app.services.game.engine import RollAction, process_action
from app.services.game.engine.events import (
    DiceRolled,
    ThreeSixesPenalty,
    TurnEnded,
)

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    PLAYER_3_ID,
    PLAYER_4_ID,
    create_player,
    create_token,
)


class TestThreeSixesPenalty:
    """Test scenarios involving three consecutive sixes."""

    def test_three_sixes_ends_turn_and_starts_next_player(self, game_player1_turn: GameState):
        """Rolling three sixes should end the turn and start the next player's turn."""
        state = game_player1_turn

        # Roll first 6
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Roll second 6
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Roll third 6 - should trigger penalty
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success

        # Verify events
        event_types = [e.event_type for e in result.events]
        assert "three_sixes_penalty" in event_types
        assert "turn_ended" in event_types
        assert "turn_started" in event_types

        # Verify penalty event
        penalty_event = next(e for e in result.events if e.event_type == "three_sixes_penalty")
        assert isinstance(penalty_event, ThreeSixesPenalty)
        assert penalty_event.player_id == PLAYER_1_ID
        assert penalty_event.rolls == [6, 6, 6]

        # Verify turn ended with correct reason
        turn_ended = next(e for e in result.events if e.event_type == "turn_ended")
        assert isinstance(turn_ended, TurnEnded)
        assert turn_ended.reason == "three_sixes"
        assert turn_ended.next_player_id == PLAYER_2_ID

        # Verify new state
        new_state = result.state
        assert new_state.current_turn.player_id == PLAYER_2_ID
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL

    def test_three_sixes_loses_accumulated_rolls(self, game_with_token_on_road: GameState):
        """When three sixes are rolled, all accumulated rolls are lost."""
        state = game_with_token_on_road

        # Roll three 6s
        for _ in range(3):
            result = process_action(state, RollAction(value=6), PLAYER_1_ID)
            assert result.success
            state = result.state

        # Player 2's turn now - they should start fresh
        assert state.current_turn.player_id == PLAYER_2_ID
        assert state.current_turn.rolls_to_allocate == []


class TestNoLegalMoves:
    """Test scenarios where player has no legal moves."""

    def test_no_legal_moves_all_in_hell_non_six(self, game_player1_turn: GameState):
        """Rolling non-6 with all tokens in HELL ends turn immediately."""
        state = game_player1_turn

        # Roll a 3 (not a get-out roll)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        # Verify events
        event_types = [e.event_type for e in result.events]
        assert "dice_rolled" in event_types
        assert "turn_ended" in event_types
        assert "turn_started" in event_types

        # Verify turn ended with correct reason
        turn_ended = next(e for e in result.events if e.event_type == "turn_ended")
        assert isinstance(turn_ended, TurnEnded)
        assert turn_ended.reason == "no_legal_moves"
        assert turn_ended.player_id == PLAYER_1_ID
        assert turn_ended.next_player_id == PLAYER_2_ID

        # Verify next player's turn
        assert result.state.current_turn.player_id == PLAYER_2_ID
        assert result.state.current_event == CurrentEvent.PLAYER_ROLL

    def test_no_legal_moves_blocked_by_board_limit(self, two_player_board_setup):
        """Token at position 55 with roll 3 cannot move (would exceed 57)."""
        # Player 1 with token in homestretch at position 55 (needs exactly 2 to win)
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

        # Roll a 3 - cannot move as it would exceed board
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        # Verify turn ended due to no legal moves
        turn_ended = next((e for e in result.events if e.event_type == "turn_ended"), None)
        assert turn_ended is not None
        assert turn_ended.reason == "no_legal_moves"


class TestRollingSix:
    """Test scenarios involving rolling a 6."""

    def test_rolling_six_grants_another_roll(self, game_player1_turn: GameState):
        """Rolling a 6 should allow the player to roll again."""
        result = process_action(game_player1_turn, RollAction(value=6), PLAYER_1_ID)

        assert result.success

        # Verify dice rolled event
        dice_rolled = next(e for e in result.events if e.event_type == "dice_rolled")
        assert isinstance(dice_rolled, DiceRolled)
        assert dice_rolled.grants_extra_roll is True

        # State should still be waiting for roll from player 1
        assert result.state.current_turn.player_id == PLAYER_1_ID
        assert result.state.current_event == CurrentEvent.PLAYER_ROLL

        # Roll should be accumulated
        assert result.state.current_turn.rolls_to_allocate == [6]

    def test_rolling_six_with_all_in_hell_waits_for_second_roll(self, game_player1_turn: GameState):
        """Rolling 6 with all tokens in hell should wait for second roll, not immediately offer move."""
        result = process_action(game_player1_turn, RollAction(value=6), PLAYER_1_ID)

        assert result.success
        # Should be waiting for another roll, not a choice
        assert result.state.current_event == CurrentEvent.PLAYER_ROLL


class TestTurnTransitions:
    """Test turn transition logic."""

    def test_turn_wraps_around_in_four_player_game(
        self, four_player_game_not_started, player1, player2, player3, player4
    ):
        """Turn order should wrap from player 4 back to player 1."""
        from app.services.game.engine import StartGameAction

        # Start the game
        result = process_action(four_player_game_not_started, StartGameAction(), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Player 1 rolls non-6, turn ends
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state
        assert state.current_turn.player_id == PLAYER_2_ID

        # Player 2 rolls non-6, turn ends
        result = process_action(state, RollAction(value=3), PLAYER_2_ID)
        assert result.success
        state = result.state
        assert state.current_turn.player_id == PLAYER_3_ID

        # Player 3 rolls non-6, turn ends
        result = process_action(state, RollAction(value=3), PLAYER_3_ID)
        assert result.success
        state = result.state
        assert state.current_turn.player_id == PLAYER_4_ID

        # Player 4 rolls non-6, turn should wrap to player 1
        result = process_action(state, RollAction(value=3), PLAYER_4_ID)
        assert result.success
        state = result.state
        assert state.current_turn.player_id == PLAYER_1_ID


class TestDiceRolledEvents:
    """Test DiceRolled event details."""

    def test_dice_rolled_event_increments_roll_number(self, game_with_token_on_road: GameState):
        """Roll number should increment with each roll in a turn."""
        state = game_with_token_on_road

        # First roll
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        dice_event_1 = next(e for e in result.events if e.event_type == "dice_rolled")
        assert dice_event_1.roll_number == 1

        # Second roll
        result = process_action(result.state, RollAction(value=6), PLAYER_1_ID)
        assert result.success
        dice_event_2 = next(e for e in result.events if e.event_type == "dice_rolled")
        assert dice_event_2.roll_number == 2


# TODO: Good to have tests
# class TestRollAccumulation:
#     """Test that rolls accumulate correctly before being used."""
#     pass

# class TestRollBoundaries:
#     """Test that only valid roll values (1-6) are accepted."""
#     pass
