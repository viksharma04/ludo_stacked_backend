"""Tests for event generation and sequencing.

Critical scenarios tested:
- Events have sequential seq numbers
- Event types match expected structure
- Event ordering is correct

TODO (Good to have):
- [ ] Test event serialization for WebSocket
- [ ] Test event replay capability
- [ ] Test event seq gap detection
- [ ] Test all event type structures
"""

from app.schemas.game_engine import GameState
from app.services.game.engine import RollAction, StartGameAction, process_action
from app.services.game.engine.events import (
    DiceRolled,
    GameStarted,
    TurnEnded,
    TurnStarted,
)

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
)


class TestEventSequencing:
    """Test that events have proper sequence numbers."""

    def test_events_have_sequential_seq_numbers(self, two_player_game_not_started: GameState):
        """Events should have sequential seq numbers starting from 0."""
        # Start the game
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)
        assert result.success

        # Check sequence numbers
        for i, event in enumerate(result.events):
            assert event.seq == i

    def test_seq_numbers_continue_across_actions(self, game_player1_turn: GameState):
        """Seq numbers should continue from where they left off."""
        state = game_player1_turn

        # First action
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        first_action_last_seq = result.events[-1].seq if result.events else -1
        state = result.state

        # Second action (Player 2's turn now)
        result = process_action(state, RollAction(value=3), PLAYER_2_ID)
        assert result.success

        # Seq should continue from previous
        if result.events:
            assert result.events[0].seq == first_action_last_seq + 1

    def test_event_seq_stored_in_state(self, two_player_game_not_started: GameState):
        """State should track next event_seq."""
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)
        assert result.success

        # State's event_seq should be next available number
        expected_next_seq = len(result.events)
        assert result.state.event_seq == expected_next_seq


class TestEventTypes:
    """Test event type structures."""

    def test_game_started_event_structure(self, two_player_game_not_started: GameState):
        """GameStarted event should have correct structure."""
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)

        game_started = next((e for e in result.events if e.event_type == "game_started"), None)
        assert game_started is not None
        assert isinstance(game_started, GameStarted)
        assert hasattr(game_started, "player_order")
        assert hasattr(game_started, "first_player_id")
        assert len(game_started.player_order) == 2

    def test_dice_rolled_event_structure(self, game_player1_turn: GameState):
        """DiceRolled event should have correct structure."""
        result = process_action(game_player1_turn, RollAction(value=4), PLAYER_1_ID)

        dice_rolled = next((e for e in result.events if e.event_type == "dice_rolled"), None)
        assert dice_rolled is not None
        assert isinstance(dice_rolled, DiceRolled)
        assert dice_rolled.player_id == PLAYER_1_ID
        assert dice_rolled.value == 4
        assert hasattr(dice_rolled, "roll_number")
        assert hasattr(dice_rolled, "grants_extra_roll")

    def test_turn_ended_event_structure(self, game_player1_turn: GameState):
        """TurnEnded event should have correct structure."""
        # Roll non-6 with all in hell to end turn
        result = process_action(game_player1_turn, RollAction(value=3), PLAYER_1_ID)

        turn_ended = next((e for e in result.events if e.event_type == "turn_ended"), None)
        assert turn_ended is not None
        assert isinstance(turn_ended, TurnEnded)
        assert turn_ended.player_id == PLAYER_1_ID
        assert hasattr(turn_ended, "reason")
        assert hasattr(turn_ended, "next_player_id")
        assert turn_ended.next_player_id == PLAYER_2_ID

    def test_turn_started_event_structure(self, game_player1_turn: GameState):
        """TurnStarted event should have correct structure."""
        # Roll non-6 with all in hell to end turn and start next
        result = process_action(game_player1_turn, RollAction(value=3), PLAYER_1_ID)

        turn_started = next((e for e in result.events if e.event_type == "turn_started"), None)
        assert turn_started is not None
        assert isinstance(turn_started, TurnStarted)
        assert turn_started.player_id == PLAYER_2_ID
        assert hasattr(turn_started, "turn_number")


class TestEventOrdering:
    """Test that events are emitted in correct order."""

    def test_game_started_then_turn_started(self, two_player_game_not_started: GameState):
        """GameStarted should come before TurnStarted."""
        result = process_action(two_player_game_not_started, StartGameAction(), PLAYER_1_ID)

        event_types = [e.event_type for e in result.events]
        game_started_idx = event_types.index("game_started")
        turn_started_idx = event_types.index("turn_started")

        assert game_started_idx < turn_started_idx

    def test_dice_rolled_before_turn_ended(self, game_player1_turn: GameState):
        """DiceRolled should come before TurnEnded."""
        result = process_action(game_player1_turn, RollAction(value=3), PLAYER_1_ID)

        event_types = [e.event_type for e in result.events]
        dice_rolled_idx = event_types.index("dice_rolled")
        turn_ended_idx = event_types.index("turn_ended")

        assert dice_rolled_idx < turn_ended_idx

    def test_turn_ended_before_next_turn_started(self, game_player1_turn: GameState):
        """TurnEnded should come before next TurnStarted."""
        result = process_action(game_player1_turn, RollAction(value=3), PLAYER_1_ID)

        event_types = [e.event_type for e in result.events]
        turn_ended_idx = event_types.index("turn_ended")
        turn_started_idx = event_types.index("turn_started")

        assert turn_ended_idx < turn_started_idx


# TODO: Good to have tests
# class TestEventSerialization:
#     """Test event serialization for WebSocket transmission."""
#
#     def test_events_serialize_to_json(self):
#         """All events should serialize to valid JSON."""
#         pass
#
# class TestEventReplay:
#     """Test event replay capability."""
#
#     def test_events_can_reconstruct_state(self):
#         """Replaying events should reconstruct the same state."""
#         pass
