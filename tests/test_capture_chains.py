"""Tests for capture chain and extra roll mechanics.

Key rules tested:
- Capturing grants extra_rolls = captured stack height
- Extra rolls from further captures accumulate (snowball)
- Extra rolls are used after all allocated rolls are consumed
- Extra roll emits RollGranted with reason="capture_bonus"
- An extra roll of 6 grants yet another roll
- Extra roll with no legal moves -> turn ends
"""

from uuid import UUID

import pytest

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Player,
    Stack,
    StackState,
    Turn,
)
from app.services.game.engine.process import process_action
from app.services.game.engine.actions import RollAction, MoveAction
from app.services.game.engine.events import (
    StackCaptured,
    StackMoved,
    RollGranted,
    AwaitingChoice,
    TurnEnded,
    TurnStarted,
    DiceRolled,
)
from app.services.game.engine.captures import grant_extra_rolls
from tests.conftest import (
    create_stack,
    create_player,
    create_stacks_in_hell,
    PLAYER_1_ID,
    PLAYER_2_ID,
)


def make_capture_game(
    p1_stacks,
    p2_stacks,
    board_setup,
    rolls=None,
    legal_moves=None,
    current_event=CurrentEvent.PLAYER_CHOICE,
    extra_rolls=0,
):
    """Create a game state ready for a move that might cause a capture."""
    player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0, stacks=p1_stacks)
    player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 26, stacks=p2_stacks)
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=False,
        rolls_to_allocate=rolls if rolls is not None else [3],
        legal_moves=legal_moves or [],
        current_turn_order=1,
        extra_rolls=extra_rolls,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=current_event,
        board_setup=board_setup,
        current_turn=turn,
    )


class TestCaptureGrantsExtraRolls:
    """Test that capturing grants extra rolls equal to the captured stack's height."""

    def test_capturing_height_1_grants_1_extra_roll(self, standard_board_setup: BoardSetup):
        """Capturing a height-1 stack should grant 1 extra roll.

        Player 1 (abs_start=0) has stack_1 at ROAD progress=3.
        Player 2 (abs_start=26) has stack_1 at ROAD progress=29.
        Player 2 abs position: (26 + 29) % 50 = 5.
        Player 1 moves stack_1 with roll=2: progress 3 + 2 = 5, abs position = 5.
        Position 5 is not a safe space, so capture occurs.
        Captured stack height = 1, so extra_rolls should be 1.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[2],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # Verify capture event was emitted
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 1
        assert capture_events[0].capturing_player_id == PLAYER_1_ID
        assert capture_events[0].captured_player_id == PLAYER_2_ID
        assert capture_events[0].grants_extra_roll is True

        # After capturing height-1 stack and consuming the only allocated roll,
        # extra roll kicks in: RollGranted with reason="capture_bonus" should be emitted
        roll_granted_events = [
            e for e in result.events
            if isinstance(e, RollGranted) and e.reason == "capture_bonus"
        ]
        assert len(roll_granted_events) == 1
        assert roll_granted_events[0].player_id == PLAYER_1_ID

        # State should be waiting for player to roll (capture bonus)
        new_state = result.state
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL
        assert new_state.current_turn.player_id == PLAYER_1_ID

    def test_capturing_height_2_grants_2_extra_rolls(self, standard_board_setup: BoardSetup):
        """Capturing a height-2 stack should grant 2 extra rolls.

        Player 1 (abs_start=0) has stack_1 at ROAD progress=3.
        Player 2 (abs_start=26) has stack_1_2 (height=2) at ROAD progress=29.
        Player 2 abs position: (26 + 29) % 50 = 5.
        Player 1 moves stack_1 with roll=2: progress 3 + 2 = 5, abs position = 5.
        Position 5 is not safe. Capturing stack height=1, captured stack height=2.
        But wait: height 1 cannot capture height 2 (capturing_size < captured_size).
        So let's use a height-2 capturing stack instead.

        Player 1 has stack_1_2 (height=2) at ROAD progress=3.
        Roll=4, effective_roll=4/2=2, new progress=5, abs=5.
        Height 2 >= height 2: capture succeeds. Extra rolls = 2.
        """
        p1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 3),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 29),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[4],
            legal_moves=["stack_1_2"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1_2", roll_value=4), PLAYER_1_ID)
        assert result.success

        # Verify capture event
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 1
        assert capture_events[0].grants_extra_roll is True

        # After the move, extra_rolls should reflect height of captured stack (2).
        # The first capture bonus roll is already consumed (decremented) when
        # RollGranted is emitted, so the remaining extra_rolls in state is 2 - 1 = 1.
        new_state = result.state
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL
        assert new_state.current_turn.extra_rolls == 1

        # A capture_bonus RollGranted should have been emitted
        roll_granted_events = [
            e for e in result.events
            if isinstance(e, RollGranted) and e.reason == "capture_bonus"
        ]
        assert len(roll_granted_events) == 1


class TestExtraRollAfterAllocatedRolls:
    """Test that extra rolls are used only after allocated rolls are consumed."""

    def test_extra_rolls_used_after_allocated_rolls_consumed(
        self, standard_board_setup: BoardSetup
    ):
        """Extra rolls should kick in only when rolls_to_allocate is empty.

        Player 1 has stack_1 at ROAD progress=3.
        No opponent at destination (progress=5 after roll=2), no capture.
        Set extra_rolls=1 and rolls=[2] with legal_moves=["stack_1"].
        After moving with roll 2, allocated rolls are consumed.
        Then extra_rolls > 0, so RollGranted(reason="capture_bonus") is emitted.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = create_stacks_in_hell(4)

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[2],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
            extra_rolls=1,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # After the allocated roll [2] is consumed, extra_rolls=1 kicks in
        roll_granted_events = [
            e for e in result.events
            if isinstance(e, RollGranted) and e.reason == "capture_bonus"
        ]
        assert len(roll_granted_events) == 1
        assert roll_granted_events[0].player_id == PLAYER_1_ID

        # State should be waiting for player to roll
        new_state = result.state
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL
        assert new_state.current_turn.player_id == PLAYER_1_ID
        # Extra rolls decremented by 1
        assert new_state.current_turn.extra_rolls == 0


class TestCaptureChainAccumulation:
    """Test that extra rolls from multiple captures accumulate (snowball)."""

    def test_extra_rolls_accumulate_from_multiple_captures(
        self, standard_board_setup: BoardSetup
    ):
        """grant_extra_rolls should add to existing extra_rolls, not replace.

        Start with extra_rolls=1. Call grant_extra_rolls(state, 2).
        New extra_rolls should be 1 + 2 = 3.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = create_stacks_in_hell(4)

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[2],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
            extra_rolls=1,
        )

        updated_state = grant_extra_rolls(state, 2)
        assert updated_state.current_turn.extra_rolls == 3

    def test_grant_extra_rolls_with_zero_initial(self, standard_board_setup: BoardSetup):
        """grant_extra_rolls from 0 should set extra_rolls to the granted count."""
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = create_stacks_in_hell(4)

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[2],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
            extra_rolls=0,
        )

        updated_state = grant_extra_rolls(state, 3)
        assert updated_state.current_turn.extra_rolls == 3


class TestExtraRollBehavior:
    """Test extra roll edge cases and interactions."""

    def test_capture_bonus_emits_roll_granted_event(self, standard_board_setup: BoardSetup):
        """After a capture consumes the last allocated roll, RollGranted with
        reason='capture_bonus' should be emitted.

        Integration test via process_action:
        Player 1 (abs_start=0) has stack_1 at ROAD progress=3.
        Player 2 (abs_start=26) has stack_1 at ROAD progress=29 (abs=5).
        Roll=2, stack_1 moves to progress=5 (abs=5). Capture occurs.
        Only one allocated roll, so after move, extra roll kicks in.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[2],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # Check the sequence of events: StackMoved, StackCaptured, RollGranted
        event_types = [type(e).__name__ for e in result.events]
        assert "StackMoved" in event_types
        assert "StackCaptured" in event_types
        assert "RollGranted" in event_types

        # The RollGranted should have reason="capture_bonus"
        roll_granted = next(
            e for e in result.events if isinstance(e, RollGranted)
        )
        assert roll_granted.reason == "capture_bonus"
        assert roll_granted.player_id == PLAYER_1_ID

    def test_extra_roll_six_grants_another_roll(self, standard_board_setup: BoardSetup):
        """Rolling a 6 on a capture bonus roll should grant yet another roll.

        Set up state at PLAYER_ROLL with no rolls_to_allocate (simulating a
        capture bonus roll). Process RollAction(value=6). The rolling code
        should emit RollGranted(reason="rolled_six") regardless of whether the
        roll originated from a capture bonus.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = create_stacks_in_hell(4)

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[],
            legal_moves=[],
            current_event=CurrentEvent.PLAYER_ROLL,
            extra_rolls=0,
        )

        # Roll a 6 during the capture bonus roll
        result = process_action(state, RollAction(value=6), PLAYER_1_ID)
        assert result.success

        # Should emit DiceRolled and RollGranted(reason="rolled_six")
        dice_rolled = [e for e in result.events if isinstance(e, DiceRolled)]
        assert len(dice_rolled) == 1
        assert dice_rolled[0].value == 6
        assert dice_rolled[0].grants_extra_roll is True

        roll_granted = [
            e for e in result.events
            if isinstance(e, RollGranted) and e.reason == "rolled_six"
        ]
        assert len(roll_granted) == 1

        # State should still be PLAYER_ROLL for the bonus roll from rolling 6
        new_state = result.state
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL
        assert new_state.current_turn.player_id == PLAYER_1_ID

    def test_extra_roll_no_legal_moves_ends_turn(self, standard_board_setup: BoardSetup):
        """If the capture bonus roll yields no legal moves, the turn should end.

        All of Player 1's stacks are in HELL. Roll value=3 (not a get_out_roll,
        which is [6]). No legal moves exist, so the turn ends.
        """
        p1_stacks = create_stacks_in_hell(4)
        p2_stacks = create_stacks_in_hell(4)

        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[],
            legal_moves=[],
            current_event=CurrentEvent.PLAYER_ROLL,
            extra_rolls=0,
        )

        # Roll 3 with all stacks in HELL (only 6 gets out)
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success

        # Turn should end because there are no legal moves
        turn_ended_events = [e for e in result.events if isinstance(e, TurnEnded)]
        assert len(turn_ended_events) == 1
        assert turn_ended_events[0].player_id == PLAYER_1_ID
        assert turn_ended_events[0].reason == "no_legal_moves"
        assert turn_ended_events[0].next_player_id == PLAYER_2_ID

        # Next player's turn should start
        turn_started_events = [e for e in result.events if isinstance(e, TurnStarted)]
        assert len(turn_started_events) == 1
        assert turn_started_events[0].player_id == PLAYER_2_ID

        # RollGranted for next player's turn start
        roll_granted = [
            e for e in result.events
            if isinstance(e, RollGranted) and e.reason == "turn_start"
        ]
        assert len(roll_granted) == 1
        assert roll_granted[0].player_id == PLAYER_2_ID

        # State should be waiting for player 2 to roll
        new_state = result.state
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL
        assert new_state.current_turn.player_id == PLAYER_2_ID

    def test_capture_during_extra_roll_accumulates(self, standard_board_setup: BoardSetup):
        """A capture during an extra roll should add more extra rolls (snowball).

        Full integration test:
        1. Player 1 has stack_1 at progress=3, extra_rolls=1, no allocated rolls.
        2. Player rolls 2 on capture bonus roll -> legal move available.
        3. Player moves stack_1 to progress=5 (abs=5), captures Player 2 stack (height=1).
        4. The capture grants 1 more extra roll, which accumulates.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 3),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = (26+29)%50 = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        # Start with no allocated rolls but 1 extra roll, at PLAYER_ROLL
        state = make_capture_game(
            p1_stacks,
            p2_stacks,
            standard_board_setup,
            rolls=[],
            legal_moves=[],
            current_event=CurrentEvent.PLAYER_ROLL,
            extra_rolls=1,
        )

        # Step 1: Roll 2 (capture bonus roll)
        result = process_action(state, RollAction(value=2), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should have legal moves (stack_1 can move with roll 2)
        assert state.current_event == CurrentEvent.PLAYER_CHOICE
        assert "stack_1" in state.current_turn.legal_moves

        # Step 2: Move stack_1 to capture Player 2's stack at abs=5
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=2), PLAYER_1_ID)
        assert result.success

        # Verify capture happened
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 1

        # The capture grants 1 extra roll. Since we started with extra_rolls=1
        # and consumed one for the roll we just used, the capture adds 1 more.
        # The post-move logic then consumes one extra roll for the RollGranted.
        # Net: extra_rolls in state should reflect the remaining bonus rolls.
        new_state = result.state
        assert new_state.current_event == CurrentEvent.PLAYER_ROLL
        assert new_state.current_turn.player_id == PLAYER_1_ID

        # A capture_bonus RollGranted should have been emitted
        roll_granted_events = [
            e for e in result.events
            if isinstance(e, RollGranted) and e.reason == "capture_bonus"
        ]
        assert len(roll_granted_events) == 1
