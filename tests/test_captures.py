"""Tests for capture scenarios.

Critical scenarios tested:
- Stack captures opponent stack
- Capture sends opponent to HELL
- Capture grants extra roll
- Safe spaces prevent captures
- Stack captures (size comparison)

TODO (Good to have):
- [ ] Test multiple capture choices
- [ ] Test capture with stack vs single stack
- [ ] Test capture on starting position
- [ ] Test capture chain (extra roll leads to another capture)
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
from app.services.game.engine.events import StackCaptured, StackUpdate

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
)


class TestBasicCapture:
    """Test basic capture mechanics."""

    def test_stack_captures_opponent_and_sends_to_hell(self, two_player_board_setup: BoardSetup):
        """Moving to opponent's position should capture them."""
        # Player 1 at progress 5, abs = 5
        # Player 2 at abs position 8 => (26 + progress) % 52 = 8 => progress = 34
        # Player 1 rolls 3 to go from abs 5 to abs 8
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
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

        # Player 2 at absolute position 8 (not a safe space)
        player2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 34),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        # Verify safe spaces don't include position 8
        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
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

        # Move the stack
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # Verify capture event
        capture_event = next((e for e in result.events if e.event_type == "stack_captured"), None)
        assert capture_event is not None
        assert isinstance(capture_event, StackCaptured)
        assert capture_event.capturing_player_id == PLAYER_1_ID
        assert capture_event.captured_player_id == PLAYER_2_ID
        assert capture_event.grants_extra_roll is True

        # Verify captured stack is in HELL
        new_state = result.state
        player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        captured_stack = next(s for s in player2.stacks if s.stack_id == "stack_1")
        assert captured_stack.state == StackState.HELL
        assert captured_stack.progress == 0

    def test_capture_grants_extra_roll(self, two_player_board_setup: BoardSetup):
        """Capturing should grant an extra roll."""
        # Set up a capture scenario
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
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

        player2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 34),  # At abs pos 8
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
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

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # Verify extra roll was granted - player should still be rolling
        new_state = result.state
        assert new_state.current_turn.player_id == PLAYER_1_ID
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL


class TestSafeSpaces:
    """Test that safe spaces prevent captures."""

    def test_no_capture_on_safe_space(self):
        """Landing on opponent at safe space should not capture."""
        # Player 1 at progress 49, abs 49
        # Player 2 at abs position 0 (a safe space)
        # Player 2: (26 + progress) % 52 = 0 => progress = 26
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 49),
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

        player2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 26),  # (26+26)%52 = 0 (safe)
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        # Safe space at 0
        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
            squares_to_win=57,
            squares_to_homestretch=52,
            starting_positions=[0, 26],
            safe_spaces=[0, 26],  # 0 is a safe space
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

        # Roll 3 to land on abs position 0 (49 + 3 = 52 % 52 = 0)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move the stack
        if "stack_1" in state.current_turn.legal_moves:
            result = process_action(
                state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID
            )
            assert result.success

            # Verify NO capture event (safe space)
            capture_events = [e for e in result.events if e.event_type == "stack_captured"]
            assert len(capture_events) == 0

            # Verify opponent stack is still on road
            new_state = result.state
            player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
            opponent_stack = next(s for s in player2.stacks if s.stack_id == "stack_1")
            assert opponent_stack.state == StackState.ROAD  # Not captured


class TestStackCaptures:
    """Test capture rules with stacks."""

    def test_stack_captures_single_token(self, two_player_board_setup: BoardSetup):
        """Stack of 2 landing on single stack should capture it.

        Also verifies that capturing_stack_id is the stack_id.
        """
        # Player 1 has a stack of height 2 at progress 3
        # Rolling 4 moves stack by 4/2=2 to position 5
        # Player 2 has a single stack at absolute position 5
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 3),
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

        # Player 2 at abs pos 5: (26 + progress) % 52 = 5 => progress = 31
        player2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 31),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
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

        # Roll 4 - stack of 2 moves by 4/2=2 to position 5
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move the stack
        result = process_action(state, MoveAction(stack_id="stack_1_2", roll_value=4), PLAYER_1_ID)
        assert result.success

        # Verify capture event
        capture_event = next((e for e in result.events if e.event_type == "stack_captured"), None)
        assert capture_event is not None
        assert isinstance(capture_event, StackCaptured)
        assert capture_event.capturing_player_id == PLAYER_1_ID
        assert capture_event.captured_player_id == PLAYER_2_ID
        # KEY: capturing_stack_id should be the stack_id
        assert capture_event.capturing_stack_id == "stack_1_2"
        assert capture_event.grants_extra_roll is True

        # Verify captured stack is in HELL
        new_state = result.state
        player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        captured_stack = next(s for s in player2.stacks if s.stack_id == "stack_1")
        assert captured_stack.state == StackState.HELL
        assert captured_stack.progress == 0

    def test_smaller_stack_cannot_capture_larger(self, two_player_board_setup: BoardSetup):
        """Single stack landing on stack of 2 should NOT capture."""
        # Player 1 has a single stack (height 1) at progress 3
        # Rolling 2 moves stack to position 5
        # Player 2 has a stack of height 2 at absolute position 5
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
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

        # Player 2 has a stack of height 2 at abs pos 5: (26 + progress) % 52 = 5 => progress = 31
        player2_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 31),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
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

        # Roll 2 - stack moves to position 5 (where P2's stack is)
        result = process_action(state, RollAction(value=2), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move the stack
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # Verify NO capture event (single stack cannot capture larger stack)
        capture_events = [e for e in result.events if e.event_type == "stack_captured"]
        assert len(capture_events) == 0

        # Verify P2's stack is still on ROAD
        new_state = result.state
        player2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        p2_stack = next(s for s in player2.stacks if s.stack_id == "stack_1_2")
        assert p2_stack.state == StackState.ROAD


class TestMultiHeightCaptureDecomposition:
    """Test that capturing a multi-height stack emits StackUpdate for decomposition."""

    def test_capturing_height_2_emits_stack_update_for_decomposition(self):
        """Capturing a height-2 stack should emit StackUpdate showing decomposition
        into individual stacks in HELL."""
        # Player 1 has height-2 stack at progress 5, capturing player 2's height-2 stack
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 3),
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

        # Player 2 has height-2 stack at abs pos 5: (26 + progress) % 52 = 5 => progress = 31
        player2_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 31),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
            squares_to_win=55,
            squares_to_homestretch=49,
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

        # Roll 4: stack_1_2 (height 2, 4/2=2) moves from 3 to 5, landing on P2's stack
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        result = process_action(
            state, MoveAction(stack_id="stack_1_2", roll_value=4), PLAYER_1_ID
        )
        assert result.success

        # StackCaptured event should exist
        capture_event = next(
            (e for e in result.events if isinstance(e, StackCaptured)), None
        )
        assert capture_event is not None

        # StackUpdate should be emitted for the decomposition of the captured stack
        update_events = [e for e in result.events if isinstance(e, StackUpdate)]
        decomp_event = next(
            (e for e in update_events if e.player_id == PLAYER_2_ID), None
        )
        assert decomp_event is not None, (
            "StackUpdate should be emitted for captured player's stack decomposition"
        )

        # remove_stacks should contain the captured composite stack
        removed_ids = {s.stack_id for s in decomp_event.remove_stacks}
        assert "stack_1_2" in removed_ids

        # add_stacks should contain the individual component stacks in HELL
        added_ids = {s.stack_id for s in decomp_event.add_stacks}
        assert "stack_1" in added_ids
        assert "stack_2" in added_ids
        for added_stack in decomp_event.add_stacks:
            assert added_stack.state == StackState.HELL
            assert added_stack.height == 1
            assert added_stack.progress == 0

    def test_capturing_height_1_no_decomposition_event(self):
        """Capturing a height-1 stack should NOT emit a StackUpdate for decomposition
        since there is nothing to decompose."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
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

        # Player 2 at abs position 8: (26 + progress) % 52 = 8 => progress = 34
        player2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 34),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="Player 2",
            color="blue",
            turn_order=2,
            abs_starting_index=26,
            stacks=player2_stacks,
        )

        board_setup = BoardSetup(
            grid_length=6,
            loop_length=52,
            squares_to_win=55,
            squares_to_homestretch=49,
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

        # Roll 3: stack_1 moves from 5 to 8, landing on P2's stack
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        result = process_action(
            state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID
        )
        assert result.success

        # StackCaptured should exist
        assert any(isinstance(e, StackCaptured) for e in result.events)

        # No StackUpdate for the captured player (height 1 has no decomposition)
        update_events = [
            e for e in result.events
            if isinstance(e, StackUpdate) and e.player_id == PLAYER_2_ID
        ]
        assert len(update_events) == 0, (
            "No StackUpdate should be emitted for height-1 capture (no decomposition)"
        )
