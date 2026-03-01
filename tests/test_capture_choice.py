"""Tests for the capture choice mechanic.

When a move lands on a square with MULTIPLE opponent stacks, the player
must choose which one to capture. Single-opponent collisions are auto-resolved
(existing behavior). Multiple opponents trigger an AwaitingCaptureChoice event
and transition to CAPTURE_CHOICE current_event state.

Key rules:
- Single opponent -> auto-resolved (no choice needed)
- Multiple opponents -> emit AwaitingCaptureChoice, transition to CAPTURE_CHOICE
- CaptureChoiceAction resolves the capture
- Options only include stacks the player CAN capture (height >= target height)
- Unchosen opponents remain on the square
- After choice, capture grants extra rolls as normal
- Invalid choice rejected

NOTE: Most tests in this file will FAIL because process_capture_choice()
is currently a placeholder in captures.py. These tests represent the
intended behavior once the mechanic is implemented.
"""

from uuid import UUID

import pytest

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    PendingCapture,
    Player,
    Stack,
    StackState,
    Turn,
)
from app.services.game.engine.process import process_action
from app.services.game.engine.actions import MoveAction, CaptureChoiceAction
from app.services.game.engine.events import (
    StackCaptured,
    StackMoved,
    AwaitingCaptureChoice,
    RollGranted,
)
from app.services.game.engine.captures import detect_collisions, resolve_collision
from tests.conftest import (
    create_stack,
    create_player,
    create_stacks_in_hell,
    PLAYER_1_ID,
    PLAYER_2_ID,
    PLAYER_3_ID,
    PLAYER_4_ID,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_four_player_game(
    p1_stacks,
    p2_stacks,
    p3_stacks,
    p4_stacks,
    board_setup,
    rolls=None,
    legal_moves=None,
    current_event=CurrentEvent.PLAYER_CHOICE,
    extra_rolls=0,
    pending_capture=None,
):
    """Build a four-player GameState with customizable stacks and turn info."""
    player1 = create_player(PLAYER_1_ID, "Player 1", "red", 1, 0, stacks=p1_stacks)
    player2 = create_player(PLAYER_2_ID, "Player 2", "blue", 2, 13, stacks=p2_stacks)
    player3 = create_player(PLAYER_3_ID, "Player 3", "green", 3, 26, stacks=p3_stacks)
    player4 = create_player(PLAYER_4_ID, "Player 4", "yellow", 4, 39, stacks=p4_stacks)
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=False,
        rolls_to_allocate=rolls or [3],
        legal_moves=legal_moves or [],
        current_turn_order=1,
        extra_rolls=extra_rolls,
        pending_capture=pending_capture,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2, player3, player4],
        current_event=current_event,
        board_setup=board_setup,
        current_turn=turn,
    )


# ---------------------------------------------------------------------------
# 1. Single opponent -> auto-resolved (existing behaviour)
# ---------------------------------------------------------------------------

class TestSingleOpponentAutoResolved:
    """When only one opponent occupies the target square, capture is automatic."""

    def test_single_opponent_captured_automatically(self, standard_board_setup: BoardSetup):
        """Player 1 moves to abs position 5 where only Player 2 sits.

        Setup (grid_length=6, squares_to_homestretch=50):
        - Player 1 (abs_start=0): stack_1 at ROAD progress=2, will move +3 -> progress=5 (abs=5)
        - Player 2 (abs_start=13): stack_1 at progress=42 -> abs=(13+42)%50=5
        - Position 5 is NOT a safe space -> capture happens.

        Expected: StackCaptured emitted, NO AwaitingCaptureChoice.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 2),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = (13+42)%50 = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=create_stacks_in_hell(),
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[3],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # A StackCaptured event should be emitted
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 1
        assert capture_events[0].capturing_player_id == PLAYER_1_ID
        assert capture_events[0].captured_player_id == PLAYER_2_ID

        # No AwaitingCaptureChoice should be emitted for a single opponent
        choice_events = [e for e in result.events if isinstance(e, AwaitingCaptureChoice)]
        assert len(choice_events) == 0

        # Captured stack should be in HELL
        new_state = result.state
        p2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        captured = next(s for s in p2.stacks if s.stack_id == "stack_1")
        assert captured.state == StackState.HELL
        assert captured.progress == 0


# ---------------------------------------------------------------------------
# 2. Multiple opponents require choice
# ---------------------------------------------------------------------------

class TestMultipleOpponentsRequireChoice:
    """When multiple opponents occupy the target square, player must choose."""

    def test_multiple_opponents_emit_awaiting_capture_choice(
        self, standard_board_setup: BoardSetup
    ):
        """Player 1 moves to abs=5 where Player 2 AND Player 3 both sit.

        Setup (squares_to_homestretch=50):
        - Player 1 (abs_start=0):  stack_1 at ROAD progress=2, move +3 -> progress=5 (abs=5)
        - Player 2 (abs_start=13): stack_1 at progress=42 -> abs=(13+42)%50=5
        - Player 3 (abs_start=26): stack_1 at progress=29 -> abs=(26+29)%50=5

        Expected:
        - Engine detects 2 opponent collisions at abs=5.
        - Emits AwaitingCaptureChoice with the two target stack options.
        - State transitions to CAPTURE_CHOICE current_event.

        NOTE: Current code processes ALL collisions in a loop and captures
        each one. This test will FAIL until the choice mechanic is implemented.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 2),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = (26+29)%50 = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[3],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # Should emit AwaitingCaptureChoice (not auto-capture both)
        choice_events = [e for e in result.events if isinstance(e, AwaitingCaptureChoice)]
        assert len(choice_events) == 1

        choice_event = choice_events[0]
        assert choice_event.player_id == PLAYER_1_ID
        # Options should list the two opponent stack targets
        assert len(choice_event.options) == 2

        # Should NOT have auto-captured both opponents
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 0

        # State should be in CAPTURE_CHOICE
        assert result.state.current_event == CurrentEvent.CAPTURE_CHOICE


# ---------------------------------------------------------------------------
# 3. Capture choice resolution
# ---------------------------------------------------------------------------

class TestCaptureChoiceResolution:
    """Processing CaptureChoiceAction resolves the pending capture."""

    def test_player_selects_target_from_options(self, standard_board_setup: BoardSetup):
        """When in CAPTURE_CHOICE, a CaptureChoiceAction with a valid target
        captures the chosen opponent and leaves the other in place.

        Setup: game already in CAPTURE_CHOICE state.
        - Player 1 (abs_start=0):  stack_1 at ROAD progress=5 (abs=5)
        - Player 2 (abs_start=13): stack_1 at progress=42 (abs=5)
        - Player 3 (abs_start=26): stack_1 at progress=29 (abs=5)

        Action: CaptureChoiceAction choosing Player 2's stack.

        Expected:
        - Player 2's stack captured (sent to HELL).
        - Player 3's stack remains on ROAD at progress=29.
        - StackCaptured event emitted for Player 2.

        NOTE: process_capture_choice() is a placeholder. This test will FAIL.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        # The target choice is Player 2's stack_1
        # The choice string should be an identifier for the target.
        # Using format: "{player_id}:stack_1"
        target_choice = f"{PLAYER_2_ID}:stack_1"

        pending = PendingCapture(
            moving_stack_id="stack_1",
            position=5,
            capturable_targets=[
                f"{PLAYER_2_ID}:stack_1",
                f"{PLAYER_3_ID}:stack_1",
            ],
        )

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[],  # Roll already consumed by the move
            legal_moves=[],
            current_event=CurrentEvent.CAPTURE_CHOICE,
            extra_rolls=0,
            pending_capture=pending,
        )

        result = process_action(
            state,
            CaptureChoiceAction(choice=target_choice),
            PLAYER_1_ID,
        )
        assert result.success

        # Verify Player 2's stack was captured
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 1
        assert capture_events[0].captured_player_id == PLAYER_2_ID
        assert capture_events[0].capturing_player_id == PLAYER_1_ID

        # Verify Player 2's stack is now in HELL
        new_state = result.state
        p2 = next(p for p in new_state.players if p.player_id == PLAYER_2_ID)
        p2_stack = next(s for s in p2.stacks if s.stack_id == "stack_1")
        assert p2_stack.state == StackState.HELL
        assert p2_stack.progress == 0

        # Verify Player 3's stack is STILL on ROAD, untouched
        p3 = next(p for p in new_state.players if p.player_id == PLAYER_3_ID)
        p3_stack = next(s for s in p3.stacks if s.stack_id == "stack_1")
        assert p3_stack.state == StackState.ROAD
        assert p3_stack.progress == 29


# ---------------------------------------------------------------------------
# 4. Capture choice validation
# ---------------------------------------------------------------------------

class TestCaptureChoiceValidation:
    """Invalid capture choices are rejected."""

    def test_invalid_capture_choice_rejected(self, standard_board_setup: BoardSetup):
        """Sending a CaptureChoiceAction with an invalid stack_id that is not
        among the available options should fail.

        NOTE: process_capture_choice() is a placeholder. This test will FAIL.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        pending = PendingCapture(
            moving_stack_id="stack_1",
            position=5,
            capturable_targets=[f"{PLAYER_2_ID}:stack_1"],
        )

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=create_stacks_in_hell(),
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[],
            legal_moves=[],
            current_event=CurrentEvent.CAPTURE_CHOICE,
            extra_rolls=0,
            pending_capture=pending,
        )

        # Send an invalid choice that doesn't correspond to any target
        result = process_action(
            state,
            CaptureChoiceAction(choice="nonexistent_target"),
            PLAYER_1_ID,
        )
        assert result.success is False

    def test_capture_choice_rejected_when_not_in_capture_choice_phase(
        self, standard_board_setup: BoardSetup
    ):
        """CaptureChoiceAction should be rejected when current_event is not CAPTURE_CHOICE."""
        state = make_four_player_game(
            p1_stacks=create_stacks_in_hell(),
            p2_stacks=create_stacks_in_hell(),
            p3_stacks=create_stacks_in_hell(),
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[3],
            legal_moves=[],
            current_event=CurrentEvent.PLAYER_ROLL,  # Wrong phase
            extra_rolls=0,
        )

        result = process_action(
            state,
            CaptureChoiceAction(choice="anything"),
            PLAYER_1_ID,
        )
        assert result.success is False
        assert result.error_code == "INVALID_ACTION"


# ---------------------------------------------------------------------------
# 5. Height filter on capture options
# ---------------------------------------------------------------------------

class TestCaptureChoiceHeightFilter:
    """Options exclude stacks that are too tall to capture."""

    def test_options_exclude_stacks_too_tall_to_capture(
        self, standard_board_setup: BoardSetup
    ):
        """Player 1 (height=1) lands on a position with:
        - Player 2: height=1 (capturable, since 1 >= 1)
        - Player 3: height=2 (NOT capturable, since 1 < 2)

        Expected: AwaitingCaptureChoice should NOT be emitted because
        only ONE opponent is actually capturable. The single capturable
        opponent (Player 2) should be auto-captured.

        Alternatively, if the engine still emits AwaitingCaptureChoice,
        its options should only contain Player 2's stack (height=1),
        NOT Player 3's stack (height=2).

        NOTE: Current code auto-captures everything in a loop.
        This test will FAIL until choice mechanic is implemented.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 2),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5, height=1
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 29),  # abs = 5, height=2
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[3],
            legal_moves=["stack_1"],
            current_event=CurrentEvent.PLAYER_CHOICE,
        )

        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # Only Player 2's stack is capturable (height 1 vs height 1).
        # Player 3's stack_1_2 (height=2) cannot be captured by a height=1 stack.
        # With only 1 capturable opponent, auto-capture should kick in:
        capture_events = [e for e in result.events if isinstance(e, StackCaptured)]
        assert len(capture_events) == 1
        assert capture_events[0].captured_player_id == PLAYER_2_ID

        # No AwaitingCaptureChoice because only one valid target
        choice_events = [e for e in result.events if isinstance(e, AwaitingCaptureChoice)]
        assert len(choice_events) == 0

        # Player 3's stack should remain on ROAD
        new_state = result.state
        p3 = next(p for p in new_state.players if p.player_id == PLAYER_3_ID)
        p3_stack = next(s for s in p3.stacks if s.stack_id == "stack_1_2")
        assert p3_stack.state == StackState.ROAD
        assert p3_stack.progress == 29


# ---------------------------------------------------------------------------
# 6. Capture choice grants extra rolls
# ---------------------------------------------------------------------------

class TestCaptureChoiceGrantsExtraRolls:
    """After resolving a capture choice, extra rolls are granted as normal."""

    def test_capture_choice_grants_extra_rolls(self, standard_board_setup: BoardSetup):
        """Resolving a capture via CaptureChoiceAction should grant extra_rolls
        equal to the captured stack's height, the same as automatic captures.

        Setup: game in CAPTURE_CHOICE. Player 1 at abs=5.
        Player 2 has stack (height=1) at abs=5.
        Player 3 has stack (height=1) at abs=5.

        Player chooses to capture Player 2's stack (height=1).
        -> Should grant 1 extra roll.

        NOTE: process_capture_choice() is a placeholder. This test will FAIL.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        target_choice = f"{PLAYER_2_ID}:stack_1"

        pending = PendingCapture(
            moving_stack_id="stack_1",
            position=5,
            capturable_targets=[
                f"{PLAYER_2_ID}:stack_1",
                f"{PLAYER_3_ID}:stack_1",
            ],
        )

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[],  # Roll already consumed
            legal_moves=[],
            current_event=CurrentEvent.CAPTURE_CHOICE,
            extra_rolls=0,
            pending_capture=pending,
        )

        result = process_action(
            state,
            CaptureChoiceAction(choice=target_choice),
            PLAYER_1_ID,
        )
        assert result.success

        # Capture should grant extra rolls
        new_state = result.state
        assert new_state.current_turn is not None

        # Extra roll granted: either through extra_rolls counter or RollGranted event
        roll_granted_events = [e for e in result.events if isinstance(e, RollGranted)]
        has_extra_roll = (
            len(roll_granted_events) > 0
            or new_state.current_turn.extra_rolls > 0
        )
        assert has_extra_roll, (
            "Capture choice should grant extra rolls equal to captured height"
        )

    def test_capture_choice_grants_extra_rolls_for_tall_stack(
        self, standard_board_setup: BoardSetup
    ):
        """Capturing a height-2 stack via choice should grant 2 extra rolls.

        Setup: Player 1 has stack of height 2 at abs=5.
        Player 2 has stack (height=2) at abs=5.
        Player 3 has stack (height=1) at abs=5.

        Player chooses to capture Player 2's stack (height=2).
        -> Should grant 2 extra rolls.

        NOTE: process_capture_choice() is a placeholder. This test will FAIL.
        """
        p1_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 5),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1_2", StackState.ROAD, 2, 42),  # abs = 5, height=2
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = 5, height=1
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        target_choice = f"{PLAYER_2_ID}:stack_1_2"

        pending = PendingCapture(
            moving_stack_id="stack_1_2",
            position=5,
            capturable_targets=[
                f"{PLAYER_2_ID}:stack_1_2",
                f"{PLAYER_3_ID}:stack_1",
            ],
        )

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
            rolls=[],
            legal_moves=[],
            current_event=CurrentEvent.CAPTURE_CHOICE,
            extra_rolls=0,
            pending_capture=pending,
        )

        result = process_action(
            state,
            CaptureChoiceAction(choice=target_choice),
            PLAYER_1_ID,
        )
        assert result.success

        # Captured stack height=2, should grant 2 extra rolls
        new_state = result.state
        assert new_state.current_turn is not None

        # The captured height-2 stack should yield 2 extra rolls total
        # (one may already be consumed as a RollGranted event leaving 1 in extra_rolls,
        # or both may be in extra_rolls)
        roll_granted_events = [e for e in result.events if isinstance(e, RollGranted)]
        total_extra = new_state.current_turn.extra_rolls + len(roll_granted_events)
        assert total_extra >= 2, (
            f"Expected at least 2 extra rolls for capturing height-2 stack, "
            f"got extra_rolls={new_state.current_turn.extra_rolls}, "
            f"roll_granted_events={len(roll_granted_events)}"
        )


# ---------------------------------------------------------------------------
# 7. detect_collisions with multiple opponents (unit test)
# ---------------------------------------------------------------------------

class TestDetectMultipleCollisions:
    """Unit tests for detect_collisions() with multiple opponents at the same position."""

    def test_detect_collisions_finds_multiple_opponents(
        self, standard_board_setup: BoardSetup
    ):
        """Three players have stacks at the same absolute position.

        Setup (squares_to_homestretch=50):
        - Player 1 (abs_start=0):  stack_1 at progress=5  -> abs=5
        - Player 2 (abs_start=13): stack_1 at progress=42 -> abs=(13+42)%50=5
        - Player 3 (abs_start=26): stack_1 at progress=29 -> abs=(26+29)%50=5
        - Player 4 (abs_start=39): stack_1 at progress=16 -> abs=(39+16)%50=5

        detect_collisions for Player 1's stack should find 3 collisions
        (Player 2, Player 3, Player 4).
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p4_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 16),  # abs = (39+16)%50 = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=p4_stacks,
            board_setup=standard_board_setup,
        )

        # The moved piece is Player 1's stack_1
        moving_player = next(p for p in state.players if p.player_id == PLAYER_1_ID)
        moved_piece = next(s for s in moving_player.stacks if s.stack_id == "stack_1")

        collisions = detect_collisions(
            state, moved_piece, moving_player, standard_board_setup
        )

        # Should find collisions with Player 2, 3, and 4 (3 total)
        assert len(collisions) == 3

        collision_player_ids = {player.player_id for player, _stack in collisions}
        assert PLAYER_2_ID in collision_player_ids
        assert PLAYER_3_ID in collision_player_ids
        assert PLAYER_4_ID in collision_player_ids

    def test_detect_collisions_finds_two_opponents(
        self, standard_board_setup: BoardSetup
    ):
        """Two opponents at the same position as the moved piece.

        Setup:
        - Player 1 (abs_start=0):  stack_1 at progress=5  -> abs=5
        - Player 2 (abs_start=13): stack_1 at progress=42 -> abs=5
        - Player 3 (abs_start=26): stack_1 at progress=29 -> abs=5
        - Player 4: all in HELL (no collision)

        detect_collisions for Player 1's stack should find 2 collisions.
        """
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p2_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 42),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
        )

        moving_player = next(p for p in state.players if p.player_id == PLAYER_1_ID)
        moved_piece = next(s for s in moving_player.stacks if s.stack_id == "stack_1")

        collisions = detect_collisions(
            state, moved_piece, moving_player, standard_board_setup
        )

        assert len(collisions) == 2

        collision_player_ids = {player.player_id for player, _stack in collisions}
        assert PLAYER_2_ID in collision_player_ids
        assert PLAYER_3_ID in collision_player_ids

    def test_detect_collisions_ignores_non_road_stacks(
        self, standard_board_setup: BoardSetup
    ):
        """Stacks in HELL, HOMESTRETCH, or HEAVEN should not count as collisions."""
        p1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 5),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        # Player 2 has a HELL stack (should not collide even if progress math matches)
        p2_stacks = [
            create_stack("stack_1", StackState.HELL, 1, 0),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        # Player 3 at abs=5 on ROAD (should collide)
        p3_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 29),  # abs = 5
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]

        state = make_four_player_game(
            p1_stacks=p1_stacks,
            p2_stacks=p2_stacks,
            p3_stacks=p3_stacks,
            p4_stacks=create_stacks_in_hell(),
            board_setup=standard_board_setup,
        )

        moving_player = next(p for p in state.players if p.player_id == PLAYER_1_ID)
        moved_piece = next(s for s in moving_player.stacks if s.stack_id == "stack_1")

        collisions = detect_collisions(
            state, moved_piece, moving_player, standard_board_setup
        )

        # Only Player 3's ROAD stack should be detected
        assert len(collisions) == 1
        assert collisions[0][0].player_id == PLAYER_3_ID
