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


# TODO: Good to have tests
# class TestStackCapture:
#     """Test stack capture behavior."""
#
#     def test_stack_dissolved_when_captured(self):
#         """Stack should be dissolved when captured."""
#         pass
#
# class TestStackLimits:
#     """Test stack size limits."""
#
#     def test_three_stack(self):
#         """Three stacks can form a stack."""
#         pass
#
#     def test_four_stack(self):
#         """Four stacks can form a stack."""
#         pass
#
# class TestStackInHomestretch:
#     """Test stack behavior in homestretch."""
#
#     def test_stack_entering_homestretch(self):
#         """Stack can enter homestretch."""
#         pass
#
#     def test_stack_reaching_heaven(self):
#         """All pieces in stack finish when stack reaches heaven."""
#         pass
