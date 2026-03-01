"""Tests for game winning and finishing scenarios.

Critical scenarios tested:
- Single stack reaches heaven
- All stacks reach heaven (game finished)
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
    StackState,
    Turn,
)
from app.services.game.engine import MoveAction, RollAction, process_action
from app.services.game.engine.events import StackReachedHeaven

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
)


class TestStackReachingHeaven:
    """Test stacks reaching the HEAVEN state (finished)."""

    def test_stack_reaches_heaven_with_exact_roll(self, two_player_board_setup: BoardSetup):
        """Stack should reach HEAVEN with exact roll to squares_to_win."""
        # Player 1 with stack at progress 53 (needs exactly 2 to win at 55)
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 53),
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

        # Roll exactly 2
        result = process_action(state, RollAction(value=2), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should have legal move
        assert state.current_event == CurrentEvent.PLAYER_CHOICE
        assert "stack_1" in state.current_turn.legal_moves

        # Make the move
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # Verify StackReachedHeaven event
        heaven_event = next(
            (e for e in result.events if e.event_type == "stack_reached_heaven"), None
        )
        assert heaven_event is not None
        assert isinstance(heaven_event, StackReachedHeaven)
        assert heaven_event.stack_id == "stack_1"

        # Verify stack state
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert stack.state == StackState.HEAVEN
        assert stack.progress == 55  # squares_to_win

    def test_cannot_overshoot_heaven(self, two_player_board_setup: BoardSetup):
        """Stack cannot move if roll would exceed squares_to_win."""
        # Player 1 with stack at progress 53 (needs exactly 2 to win at 55)
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 53),
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

        # Roll a 5 (would overshoot 55)
        result = process_action(state, RollAction(value=5), PLAYER_1_ID)
        assert result.success

        # Turn should end - no legal moves
        event_types = [e.event_type for e in result.events]
        assert "turn_ended" in event_types

    def test_stack_in_homestretch_state(self, two_player_board_setup: BoardSetup):
        """Stack should transition to HOMESTRETCH state when entering final stretch."""
        # Player 1 with stack at progress 48 (enters homestretch at 50)
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 48),
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

        # Roll 3 (48 + 3 = 51, enters homestretch at 50)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Make the move
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # Verify stack is now in HOMESTRETCH
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in player1.stacks if s.stack_id == "stack_1")
        assert stack.state == StackState.HOMESTRETCH
        assert stack.progress == 51


class TestAllStacksInHeaven:
    """Test scenarios where all stacks reach heaven."""

    def test_last_stack_reaching_heaven(self, two_player_board_setup: BoardSetup):
        """When last stack reaches heaven, appropriate events should fire."""
        # Player 1 with 3 stacks in heaven, 1 about to finish
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 53),  # Needs 2
            create_stack("stack_2", StackState.HEAVEN, 1, 55),
            create_stack("stack_3", StackState.HEAVEN, 1, 55),
            create_stack("stack_4", StackState.HEAVEN, 1, 55),
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

        # Roll 2 and move last stack
        result = process_action(state, RollAction(value=2), PLAYER_1_ID)
        state = result.state

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # Verify StackReachedHeaven event
        heaven_event = next(
            (e for e in result.events if e.event_type == "stack_reached_heaven"), None
        )
        assert heaven_event is not None

        # Verify all stacks are in heaven
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        assert all(s.state == StackState.HEAVEN for s in player1.stacks)


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
#     def test_stack_reaching_heaven_finishes_all_pieces(self):
#         """All pieces in a stack should finish when stack reaches heaven."""
#         pass
