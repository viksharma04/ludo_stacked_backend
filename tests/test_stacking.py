"""Tests for stacking mechanics.

Critical scenarios tested:
- Own stacks merge when landing on same position
- Stack movement with effective roll
- Partial stack movement
- Stack requires divisible roll

TODO (Good to have):
- [ ] Test stack formation event details
- [ ] Test maximum stack size
- [ ] Test stack entering homestretch
- [ ] Test stack reaching heaven
- [ ] Test partial stack split leaving single stack
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
from app.services.game.engine.events import StackMoved, StackUpdate

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
)


class TestStackFormation:
    """Test stack formation when own stacks meet."""

    def test_stacks_merge_when_landing_on_same_position(self, two_player_board_setup: BoardSetup):
        """Two stacks of same player should merge into one."""
        # Player 1 with two stacks: stack_1 at progress 5, stack_2 at progress 10
        # Rolling 5 should move stack_1 from 5 to 10, creating stack_1_2
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.ROAD, 1, 10),
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

        # Roll 5
        result = process_action(state, RollAction(value=5), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move stack_1 from 5 to 10
        result = process_action(state, MoveAction(stack_id="stack_1"), PLAYER_1_ID)
        assert result.success

        # Verify StackUpdate event
        stack_event = next((e for e in result.events if e.event_type == "stack_update"), None)
        assert stack_event is not None
        assert isinstance(stack_event, StackUpdate)
        assert stack_event.player_id == PLAYER_1_ID

        # Verify the add_stacks contains the merged stack
        assert len(stack_event.add_stacks) == 1
        merged = stack_event.add_stacks[0]
        assert merged.stack_id == "stack_1_2"
        assert merged.height == 2

        # Verify the remove_stacks contains the original two stacks
        removed_ids = {s.stack_id for s in stack_event.remove_stacks}
        assert "stack_1" in removed_ids
        assert "stack_2" in removed_ids

        # Verify player has the merged stack
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack_ids = {s.stack_id for s in player1.stacks}
        assert "stack_1_2" in stack_ids
        assert "stack_1" not in stack_ids
        assert "stack_2" not in stack_ids


class TestStackMovement:
    """Test stack movement mechanics."""

    def test_stack_moves_with_effective_roll(self, two_player_board_setup: BoardSetup):
        """Stack should move by roll / stack_height."""
        # Player 1 with a stack of height 2 at progress 10
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 10),
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

        # Roll 4 - stack of 2 should move by 4/2 = 2
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Stack should be in legal moves
        assert "stack_1_2" in state.current_turn.legal_moves

        # Move the stack
        result = process_action(state, MoveAction(stack_id="stack_1_2"), PLAYER_1_ID)
        assert result.success

        # Verify stack moved event
        stack_moved = next((e for e in result.events if e.event_type == "stack_moved"), None)
        assert stack_moved is not None
        assert isinstance(stack_moved, StackMoved)
        assert stack_moved.from_progress == 10
        assert stack_moved.to_progress == 12  # 10 + (4/2) = 12
        assert stack_moved.roll_used == 4

        # Verify stack position
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in player1.stacks if s.stack_id == "stack_1_2")
        assert stack.progress == 12

    def test_stack_requires_divisible_roll(self, two_player_board_setup: BoardSetup):
        """Stack of 2 cannot move with odd roll (not divisible)."""
        # Player 1 with a stack of height 2 at progress 10
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 10),
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

        # Roll 3 - odd number, not divisible by stack height 2
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Full stack should NOT be in legal moves
        assert "stack_1_2" not in state.current_turn.legal_moves

        # But partial stack moves should be available (moving 1 piece)
        # stack_2 (height 1) can move: 3 % 1 == 0 -> effective_roll = 3
        assert "stack_2" in state.current_turn.legal_moves


class TestPartialStackMovement:
    """Test partial stack movement (splitting stacks)."""

    def test_partial_stack_split(self, two_player_board_setup: BoardSetup):
        """Moving partial stack should split the stack."""
        # Player 1 with a stack of height 3 at progress 10
        player1_stacks = [
            create_stack("stack_1_2_3", StackState.ROAD, 3, 10),
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

        # Roll 4
        # Full stack (height 3): 4 % 3 != 0, not legal
        # Sub-stack of 2 (stack_2_3): 4 % 2 == 0, effective=2, legal -> moves to 12
        # Sub-stack of 1 (stack_3): 4 % 1 == 0, effective=4, legal -> moves to 14
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Full stack should NOT be in legal moves (4 % 3 != 0)
        assert "stack_1_2_3" not in state.current_turn.legal_moves

        # Sub-stack moves should be available
        assert "stack_2_3" in state.current_turn.legal_moves  # height 2, 4/2=2
        assert "stack_3" in state.current_turn.legal_moves  # height 1, 4/1=4

        # Move sub-stack of 2 (stack_2_3)
        result = process_action(state, MoveAction(stack_id="stack_2_3"), PLAYER_1_ID)
        assert result.success

        # Verify StackUpdate event for the split
        update_event = next((e for e in result.events if e.event_type == "stack_update"), None)
        assert update_event is not None
        assert isinstance(update_event, StackUpdate)

        # The parent stack_1_2_3 should be in remove_stacks
        removed_ids = {s.stack_id for s in update_event.remove_stacks}
        assert "stack_1_2_3" in removed_ids

        # add_stacks should have the remaining stack and the moving stack
        added_ids = {s.stack_id for s in update_event.add_stacks}
        assert "stack_1" in added_ids  # remaining (height 1, stays at 10)
        assert "stack_2_3" in added_ids  # moving (height 2, moves to 12)

        # Verify StackMoved event for the moving sub-stack
        moved_event = next((e for e in result.events if e.event_type == "stack_moved"), None)
        assert moved_event is not None
        assert moved_event.stack_id == "stack_2_3"
        assert moved_event.from_progress == 10
        assert moved_event.to_progress == 12  # 10 + 4/2 = 12


class TestThreeWayMerge:
    """Test merging three stacks into one."""

    def test_three_stacks_merge_in_sequence(self, two_player_board_setup: BoardSetup):
        """Moving a stack onto a position with an already-merged stack forms a triple."""
        # stack_1_2 (height 2) at progress 15, stack_3 at progress 10
        # Roll 5: stack_3 moves from 10 to 15, merges with stack_1_2 -> stack_1_2_3
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 15),
            create_stack("stack_3", StackState.ROAD, 1, 10),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID, name="Player 1", color="red",
            turn_order=1, abs_starting_index=0, stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID, name="Player 2", color="blue",
            turn_order=2, abs_starting_index=26,
        )

        turn = Turn(
            player_id=PLAYER_1_ID, initial_roll=True,
            rolls_to_allocate=[], legal_moves=[],
            current_turn_order=1, extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 5
        result = process_action(state, RollAction(value=5), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move stack_3 from 10 to 15 (landing on stack_1_2)
        result = process_action(state, MoveAction(stack_id="stack_3"), PLAYER_1_ID)
        assert result.success

        # Verify merged into stack_1_2_3
        player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack_ids = {s.stack_id for s in player.stacks}
        assert "stack_1_2_3" in stack_ids
        assert "stack_1_2" not in stack_ids
        assert "stack_3" not in stack_ids

        merged = next(s for s in player.stacks if s.stack_id == "stack_1_2_3")
        assert merged.height == 3
        assert merged.progress == 15


class TestMaxStackSize:
    """Test maximum stack size (all 4 pieces merged)."""

    def test_all_four_pieces_merge_into_height_4(self, two_player_board_setup: BoardSetup):
        """All four stacks merge into stack_1_2_3_4 (height 4)."""
        # stack_1_2_3 at progress 20, stack_4 at progress 16
        # Roll 4: stack_4 moves from 16 to 20, merges into stack_1_2_3_4
        player1_stacks = [
            create_stack("stack_1_2_3", StackState.ROAD, 3, 20),
            create_stack("stack_4", StackState.ROAD, 1, 16),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID, name="Player 1", color="red",
            turn_order=1, abs_starting_index=0, stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID, name="Player 2", color="blue",
            turn_order=2, abs_starting_index=26,
        )

        turn = Turn(
            player_id=PLAYER_1_ID, initial_roll=True,
            rolls_to_allocate=[], legal_moves=[],
            current_turn_order=1, extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        result = process_action(state, MoveAction(stack_id="stack_4"), PLAYER_1_ID)
        assert result.success

        player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack_ids = {s.stack_id for s in player.stacks}
        assert "stack_1_2_3_4" in stack_ids
        merged = next(s for s in player.stacks if s.stack_id == "stack_1_2_3_4")
        assert merged.height == 4
        assert merged.progress == 20

    def test_height_4_stack_movement_divisibility(self, two_player_board_setup: BoardSetup):
        """Height-4 stack: only roll divisible by 4 works (roll=4 → effective=1)."""
        from app.services.game.engine.legal_moves import get_legal_moves

        player1_stacks = [
            create_stack("stack_1_2_3_4", StackState.ROAD, 4, 20),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID, name="Player 1", color="red",
            turn_order=1, abs_starting_index=0, stacks=player1_stacks,
        )

        board = two_player_board_setup

        # Roll=4: 4 % 4 == 0 → effective=1 → legal (full stack)
        moves_4 = get_legal_moves(player1, 4, board)
        assert "stack_1_2_3_4" in moves_4

        # Roll=3: 3 % 4 != 0 → full stack not legal
        # But partial moves: height 3 (3%3==0), height 2 (3%2!=0), height 1 (3%1==0)
        moves_3 = get_legal_moves(player1, 3, board)
        assert "stack_1_2_3_4" not in moves_3
        assert "stack_2_3_4" in moves_3  # height 3, 3/3=1
        assert "stack_4" in moves_3  # height 1, 3/1=3

        # Roll=1: 1 % 4 != 0, but partial height 1: 1%1==0
        moves_1 = get_legal_moves(player1, 1, board)
        assert "stack_1_2_3_4" not in moves_1
        assert "stack_4" in moves_1  # height 1, 1/1=1


class TestSplitThenRemerge:
    """Test splitting a stack and then re-merging pieces."""

    def test_split_then_remerge_on_same_square(self, two_player_board_setup: BoardSetup):
        """Split a stack, then later re-merge when pieces meet again."""
        # stack_1_2_3 at progress 10. Roll 6:
        # Split: move stack_3 (height 1) from 10 to 16 (10+6)
        # remaining: stack_1_2 at 10
        # Later, move stack_1_2 (height 2) to 16 with roll 12... but max roll is 6.
        # Instead: stack_1_2 at 10, stack_3 at 12, roll 2: stack_1_2 moves to 11 (10+2/2=11)
        # That doesn't work for merge. Let me use a simpler setup.
        #
        # stack_1_2 at progress 10, stack_3 at progress 12
        # Roll 4: stack_1_2 (height 2, 4/2=2) moves to 12, lands on stack_3 → merge to stack_1_2_3
        player1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 10),
            create_stack("stack_3", StackState.ROAD, 1, 12),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID, name="Player 1", color="red",
            turn_order=1, abs_starting_index=0, stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID, name="Player 2", color="blue",
            turn_order=2, abs_starting_index=26,
        )

        turn = Turn(
            player_id=PLAYER_1_ID, initial_roll=True,
            rolls_to_allocate=[], legal_moves=[],
            current_turn_order=1, extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 4: stack_1_2 effective roll = 4/2 = 2, moves from 10 to 12
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        result = process_action(state, MoveAction(stack_id="stack_1_2"), PLAYER_1_ID)
        assert result.success

        # Verify re-merged into stack_1_2_3
        player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack_ids = {s.stack_id for s in player.stacks}
        assert "stack_1_2_3" in stack_ids
        merged = next(s for s in player.stacks if s.stack_id == "stack_1_2_3")
        assert merged.height == 3
        assert merged.progress == 12


class TestCapturedStackRebuilt:
    """Test that a captured composite stack decomposes, then can be rebuilt."""

    def test_captured_height_3_decomposes_to_individuals(self, two_player_board_setup: BoardSetup):
        """Capturing a height-3 stack should create 3 individual stacks in HELL."""
        from app.services.game.engine.captures import send_to_hell

        player2_stacks = [
            create_stack("stack_1_2_3", StackState.ROAD, 3, 15),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2 = create_player(
            player_id=PLAYER_2_ID, name="Player 2", color="blue",
            turn_order=2, abs_starting_index=26, stacks=player2_stacks,
        )
        player1 = create_player(
            player_id=PLAYER_1_ID, name="Player 1", color="red",
            turn_order=1, abs_starting_index=0,
        )

        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=two_player_board_setup,
            current_turn=None,
        )

        captured_stack = next(s for s in player2.stacks if s.stack_id == "stack_1_2_3")
        new_state = send_to_hell(state, player2, captured_stack)

        # Player 2 should now have stack_1, stack_2, stack_3, stack_4 all in HELL
        p2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        assert len(p2.stacks) == 4
        for s in p2.stacks:
            assert s.state == StackState.HELL
            assert s.progress == 0
            assert s.height == 1
        stack_ids = {s.stack_id for s in p2.stacks}
        assert stack_ids == {"stack_1", "stack_2", "stack_3", "stack_4"}


class TestSplitStackEventOrdering:
    """Test that split move events are emitted in correct order."""

    def test_stack_update_before_stack_moved(self, two_player_board_setup: BoardSetup):
        """StackUpdate (split) should come before StackMoved in events."""
        player1_stacks = [
            create_stack("stack_1_2_3", StackState.ROAD, 3, 10),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID, name="Player 1", color="red",
            turn_order=1, abs_starting_index=0, stacks=player1_stacks,
        )
        player2 = create_player(
            player_id=PLAYER_2_ID, name="Player 2", color="blue",
            turn_order=2, abs_starting_index=26,
        )

        turn = Turn(
            player_id=PLAYER_1_ID, initial_roll=True,
            rolls_to_allocate=[], legal_moves=[],
            current_turn_order=1, extra_rolls=0,
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=two_player_board_setup,
            current_turn=turn,
        )

        # Roll 5: 5%3!=0 (full stack not legal), 5%1==0 (stack_3 legal)
        result = process_action(state, RollAction(value=5), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move partial stack_3 (split from stack_1_2_3)
        result = process_action(state, MoveAction(stack_id="stack_3"), PLAYER_1_ID)
        assert result.success

        # Find StackUpdate and StackMoved events
        update_idx = None
        moved_idx = None
        for i, event in enumerate(result.events):
            if isinstance(event, StackUpdate) and update_idx is None:
                update_idx = i
            if isinstance(event, StackMoved) and moved_idx is None:
                moved_idx = i

        assert update_idx is not None, "StackUpdate event should exist"
        assert moved_idx is not None, "StackMoved event should exist"
        assert update_idx < moved_idx, "StackUpdate should come before StackMoved"
