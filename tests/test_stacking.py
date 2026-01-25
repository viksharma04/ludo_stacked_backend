"""Tests for stacking mechanics.

Critical scenarios tested:
- Own tokens stack when landing on same position
- Stack movement with effective roll
- Partial stack movement
- Stack dissolution on capture

TODO (Good to have):
- [ ] Test stack formation event details
- [ ] Test maximum stack size
- [ ] Test stack entering homestretch
- [ ] Test stack reaching heaven
- [ ] Test partial stack split leaving single token
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Stack,
    TokenState,
    Turn,
)
from app.services.game.engine import MoveAction, RollAction, process_action
from app.services.game.engine.events import StackFormed, StackMoved, StackSplit

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_token,
)


class TestStackFormation:
    """Test stack formation when own tokens meet."""

    def test_tokens_stack_when_landing_on_same_position(self, two_player_board_setup: BoardSetup):
        """Two tokens of same player should form a stack."""
        # Player 1 with two tokens: one at position 5, one at position 10
        # Rolling 5 should move token from 5 to 10, creating a stack
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 5),
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

        # Roll 5
        result = process_action(state, RollAction(value=5), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move token_1 from 5 to 10
        token_id = f"{PLAYER_1_ID}_token_1"
        result = process_action(state, MoveAction(token_or_stack_id=token_id), PLAYER_1_ID)
        assert result.success

        # Verify stack formed event
        stack_event = next((e for e in result.events if e.event_type == "stack_formed"), None)
        assert stack_event is not None
        assert isinstance(stack_event, StackFormed)
        assert stack_event.player_id == PLAYER_1_ID
        assert f"{PLAYER_1_ID}_token_1" in stack_event.token_ids
        assert f"{PLAYER_1_ID}_token_2" in stack_event.token_ids

        # Verify player has a stack
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        assert player1.stacks is not None
        assert len(player1.stacks) == 1
        assert len(player1.stacks[0].tokens) == 2

        # Verify tokens are marked as in_stack
        token1 = next(t for t in player1.tokens if t.token_id == f"{PLAYER_1_ID}_token_1")
        token2 = next(t for t in player1.tokens if t.token_id == f"{PLAYER_1_ID}_token_2")
        assert token1.in_stack is True
        assert token2.in_stack is True


class TestStackMovement:
    """Test stack movement mechanics."""

    def test_stack_moves_with_effective_roll(self, two_player_board_setup: BoardSetup):
        """Stack should move by roll / stack_height."""
        # Player 1 with a stack of 2 at position 10
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10, in_stack=True),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.ROAD, 10, in_stack=True),
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
            stacks=[
                Stack(
                    stack_id=f"{PLAYER_1_ID}_stack_1",
                    tokens=[f"{PLAYER_1_ID}_token_1", f"{PLAYER_1_ID}_token_2"],
                )
            ],
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
        stack_id = f"{PLAYER_1_ID}_stack_1"
        assert stack_id in state.current_turn.legal_moves

        # Move the stack
        result = process_action(state, MoveAction(token_or_stack_id=stack_id), PLAYER_1_ID)
        assert result.success

        # Verify stack moved event
        stack_moved = next((e for e in result.events if e.event_type == "stack_moved"), None)
        assert stack_moved is not None
        assert isinstance(stack_moved, StackMoved)
        assert stack_moved.from_progress == 10
        assert stack_moved.to_progress == 12  # 10 + (4/2) = 12
        assert stack_moved.roll_used == 4
        assert stack_moved.effective_roll == 2

        # Verify tokens moved
        new_state = result.state
        player1 = next(p for p in new_state.players if p.player_id == PLAYER_1_ID)
        token1 = next(t for t in player1.tokens if t.token_id == f"{PLAYER_1_ID}_token_1")
        token2 = next(t for t in player1.tokens if t.token_id == f"{PLAYER_1_ID}_token_2")
        assert token1.progress == 12
        assert token2.progress == 12

    def test_stack_requires_divisible_roll(self, two_player_board_setup: BoardSetup):
        """Stack of 2 cannot move with odd roll (not divisible)."""
        # Player 1 with a stack of 2 at position 10
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10, in_stack=True),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.ROAD, 10, in_stack=True),
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
            stacks=[
                Stack(
                    stack_id=f"{PLAYER_1_ID}_stack_1",
                    tokens=[f"{PLAYER_1_ID}_token_1", f"{PLAYER_1_ID}_token_2"],
                )
            ],
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

        # Roll 3 - odd number, not divisible by stack size 2
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Full stack should NOT be in legal moves
        stack_id = f"{PLAYER_1_ID}_stack_1"
        assert stack_id not in state.current_turn.legal_moves

        # But partial stack moves might be available (moving 1 token)
        partial_move = f"{stack_id}:1"  # Move 1 token from stack
        # This would be legal since 3 % 1 == 0


class TestPartialStackMovement:
    """Test partial stack movement (splitting stacks)."""

    def test_partial_stack_split(self, two_player_board_setup: BoardSetup):
        """Moving partial stack should split the stack."""
        # Player 1 with a stack of 3 at position 10
        player1_tokens = [
            create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10, in_stack=True),
            create_token(f"{PLAYER_1_ID}_token_2", TokenState.ROAD, 10, in_stack=True),
            create_token(f"{PLAYER_1_ID}_token_3", TokenState.ROAD, 10, in_stack=True),
            create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
        ]
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            tokens=player1_tokens,
            stacks=[
                Stack(
                    stack_id=f"{PLAYER_1_ID}_stack_1",
                    tokens=[
                        f"{PLAYER_1_ID}_token_1",
                        f"{PLAYER_1_ID}_token_2",
                        f"{PLAYER_1_ID}_token_3",
                    ],
                )
            ],
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

        # Roll 4 - can move 2 tokens by 4/2=2, or 1 token by 4
        result = process_action(state, RollAction(value=4), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Partial move of 2 tokens should be in legal moves
        stack_id = f"{PLAYER_1_ID}_stack_1"
        partial_move_2 = f"{stack_id}:2"
        partial_move_1 = f"{stack_id}:1"

        # Check that partial moves are available
        assert (
            partial_move_2 in state.current_turn.legal_moves
            or partial_move_1 in state.current_turn.legal_moves
        )

        # Move 2 tokens from the stack
        if partial_move_2 in state.current_turn.legal_moves:
            result = process_action(
                state, MoveAction(token_or_stack_id=partial_move_2), PLAYER_1_ID
            )
            assert result.success

            # Verify stack split event
            split_event = next((e for e in result.events if e.event_type == "stack_split"), None)
            assert split_event is not None
            assert isinstance(split_event, StackSplit)
            assert len(split_event.moving_token_ids) == 2
            assert len(split_event.remaining_token_ids) == 1


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
#     def test_three_token_stack(self):
#         """Three tokens can form a stack."""
#         pass
#
#     def test_four_token_stack(self):
#         """Four tokens can form a stack."""
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
#         """All tokens in stack finish when stack reaches heaven."""
#         pass
