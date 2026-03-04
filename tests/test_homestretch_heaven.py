"""Tests for homestretch and heaven mechanics.

Critical scenarios tested:
- Stack entry into homestretch at boundary (progress >= squares_to_homestretch)
- Stack state transitions: ROAD -> HOMESTRETCH -> HEAVEN
- Exact roll required to reach heaven (cannot overshoot)
- Split stack partial moves reaching heaven
- Stacking (merging) in homestretch
- Homestretch privacy (no opponent collisions)
- Win condition (all stacks in HEAVEN)
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Stack,
    StackState,
    Turn,
)
from app.services.game.engine.actions import MoveAction, RollAction
from app.services.game.engine.captures import detect_collisions
from app.services.game.engine.events import (
    StackMoved,
    StackReachedHeaven,
    StackUpdate,
)
from app.services.game.engine.legal_moves import get_legal_moves
from app.services.game.engine.movement import apply_stack_move
from app.services.game.engine.process import check_win_condition, process_action

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
    create_stacks_in_hell,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_two_player_state(
    player1_stacks: list[Stack],
    board_setup: BoardSetup,
    player2_stacks: list[Stack] | None = None,
    current_event: CurrentEvent = CurrentEvent.PLAYER_ROLL,
) -> GameState:
    """Build a minimal two-player IN_PROGRESS state with player 1's turn."""
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
        stacks=player2_stacks if player2_stacks is not None else create_stacks_in_hell(),
    )
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=True,
        rolls_to_allocate=[],
        legal_moves=[],
        current_turn_order=1,
        extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=current_event,
        board_setup=board_setup,
        current_turn=turn,
    )


# ===========================================================================
# 1. Homestretch Entry
# ===========================================================================


class TestHomestretchEntry:
    """Test that stacks transition to HOMESTRETCH at the boundary."""

    def test_stack_enters_homestretch_at_boundary(self, standard_board_setup: BoardSetup):
        """Stack at ROAD progress=47 rolling 3 -> progress=50 >= squares_to_homestretch.
        State should become HOMESTRETCH."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 47),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1",
            roll=3,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert stack.progress == 50
        assert stack.state == StackState.HOMESTRETCH

        # Verify StackMoved event records the transition
        moved = next((e for e in result.events if isinstance(e, StackMoved)), None)
        assert moved is not None
        assert moved.from_state == StackState.ROAD
        assert moved.to_state == StackState.HOMESTRETCH

    def test_stack_stays_road_before_boundary(self, standard_board_setup: BoardSetup):
        """Stack at ROAD progress=47 rolling 2 -> progress=49 < 50.
        State should remain ROAD."""
        player1_stacks = [
            create_stack("stack_1", StackState.ROAD, 1, 47),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1",
            roll=2,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert stack.progress == 49
        assert stack.state == StackState.ROAD

    def test_stack_progresses_through_homestretch(self, standard_board_setup: BoardSetup):
        """Stack at HOMESTRETCH progress=51 rolling 2 -> progress=53.
        State should remain HOMESTRETCH."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 51),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1",
            roll=2,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert stack.progress == 53
        assert stack.state == StackState.HOMESTRETCH


# ===========================================================================
# 2. Reaching Heaven
# ===========================================================================


class TestReachingHeaven:
    """Test exact-roll heaven entry and overshoot prevention."""

    def test_stack_reaches_heaven_exact_roll(self, standard_board_setup: BoardSetup):
        """Stack at HOMESTRETCH progress=52, roll=3. 52+3=55=squares_to_win.
        State becomes HEAVEN. StackReachedHeaven event emitted."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1",
            roll=3,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success

        # Stack should be in HEAVEN
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert stack.state == StackState.HEAVEN
        assert stack.progress == 55

        # StackReachedHeaven event should be emitted
        heaven_event = next((e for e in result.events if isinstance(e, StackReachedHeaven)), None)
        assert heaven_event is not None
        assert heaven_event.player_id == PLAYER_1_ID
        assert heaven_event.stack_id == "stack_1"

        # StackMoved event should also be emitted with correct states
        moved = next((e for e in result.events if isinstance(e, StackMoved)), None)
        assert moved is not None
        assert moved.from_state == StackState.HOMESTRETCH
        assert moved.to_state == StackState.HEAVEN
        assert moved.from_progress == 52
        assert moved.to_progress == 55

    def test_cannot_overshoot_heaven(self, standard_board_setup: BoardSetup):
        """Stack at HOMESTRETCH progress=53. Roll=3 would give 56>55.
        get_legal_moves should NOT include this stack for roll=3.
        It should include it for roll=2 (53+2=55, exact)."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 53),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )

        # Roll 3: 53 + 3 = 56 > 55, should NOT be legal
        moves_roll_3 = get_legal_moves(player, 3, standard_board_setup)
        assert "stack_1" not in moves_roll_3

        # Roll 2: 53 + 2 = 55 = squares_to_win, should be legal
        moves_roll_2 = get_legal_moves(player, 2, standard_board_setup)
        assert "stack_1" in moves_roll_2

    def test_split_stack_partial_reaches_heaven(self, standard_board_setup: BoardSetup):
        """Stack stack_1_2 (height=2) at HOMESTRETCH progress=53.

        Roll=4: full stack effective=4/2=2, 53+2=55 -> HEAVEN. Legal.
        Roll=2: full stack effective=2/2=1, 53+1=54. Legal but not heaven.
                partial stack_2 (height=1) effective=2/1=2, 53+2=55 -> HEAVEN. Legal.
        """
        player1_stacks = [
            create_stack("stack_1_2", StackState.HOMESTRETCH, 2, 53),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player = create_player(
            player_id=PLAYER_1_ID,
            name="Player 1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=player1_stacks,
        )

        # Roll 4: full stack (height 2): 4/2=2, 53+2=55 -> legal
        moves_roll_4 = get_legal_moves(player, 4, standard_board_setup)
        assert "stack_1_2" in moves_roll_4

        # Roll 2: full stack (height 2): 2/2=1, 53+1=54 -> legal
        # Roll 2: partial stack_2 (height 1): 2/1=2, 53+2=55 -> legal
        moves_roll_2 = get_legal_moves(player, 2, standard_board_setup)
        assert "stack_1_2" in moves_roll_2  # full stack can move to 54
        assert "stack_2" in moves_roll_2  # partial splits off, reaches heaven


# ===========================================================================
# 3. Homestretch Stacking (merging own stacks)
# ===========================================================================


class TestHomestretchStacking:
    """Test that own stacks can merge within the homestretch."""

    def test_own_stacks_merge_on_homestretch(self, standard_board_setup: BoardSetup):
        """Player has stack_1 at HOMESTRETCH progress=51 and stack_2 at
        HOMESTRETCH progress=50. Roll=1 moves stack_2 to progress=51,
        landing on stack_1 and triggering a merge into stack_1_2."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 51),
            create_stack("stack_2", StackState.HOMESTRETCH, 1, 50),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        # Roll 1
        result = process_action(state, RollAction(value=1), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Both stacks should be legal for roll=1
        assert "stack_1" in state.current_turn.legal_moves
        assert "stack_2" in state.current_turn.legal_moves

        # Move stack_2 from progress 50 to 51 (landing on stack_1)
        result = process_action(state, MoveAction(stack_id="stack_2", roll_value=1), PLAYER_1_ID)
        assert result.success

        # Verify StackUpdate event shows merge
        update_event = next((e for e in result.events if isinstance(e, StackUpdate)), None)
        assert update_event is not None
        assert update_event.player_id == PLAYER_1_ID

        # Merged stack should be created
        added_ids = {s.stack_id for s in update_event.add_stacks}
        assert "stack_1_2" in added_ids

        # Original stacks should be removed
        removed_ids = {s.stack_id for s in update_event.remove_stacks}
        assert "stack_1" in removed_ids
        assert "stack_2" in removed_ids

        # Verify final state
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack_ids = {s.stack_id for s in updated_player.stacks}
        assert "stack_1_2" in stack_ids
        assert "stack_1" not in stack_ids
        assert "stack_2" not in stack_ids

        merged_stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1_2")
        assert merged_stack.height == 2
        assert merged_stack.progress == 51
        assert merged_stack.state == StackState.HOMESTRETCH

    def test_three_stacks_merge_on_homestretch(self, standard_board_setup: BoardSetup):
        """Three stacks at the same homestretch progress should all merge.

        Player has stack_1 and stack_3 at HOMESTRETCH progress=51,
        and stack_2 at HOMESTRETCH progress=50. Roll=1 moves stack_2
        to progress=51, landing on both stack_1 and stack_3.
        All three should merge into stack_1_2_3.
        """
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 51),
            create_stack("stack_2", StackState.HOMESTRETCH, 1, 50),
            create_stack("stack_3", StackState.HOMESTRETCH, 1, 51),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        # Roll 1
        result = process_action(state, RollAction(value=1), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move stack_2 from progress 50 to 51 (landing on stack_1 and stack_3)
        result = process_action(state, MoveAction(stack_id="stack_2", roll_value=1), PLAYER_1_ID)
        assert result.success

        # Verify final state: all three stacks merged into stack_1_2_3
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack_ids = {s.stack_id for s in updated_player.stacks}
        assert "stack_1_2_3" in stack_ids, f"Expected stack_1_2_3 but got {stack_ids}"
        assert "stack_1" not in stack_ids
        assert "stack_2" not in stack_ids
        assert "stack_3" not in stack_ids

        merged_stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1_2_3")
        assert merged_stack.height == 3
        assert merged_stack.progress == 51
        assert merged_stack.state == StackState.HOMESTRETCH

    def test_merged_stack_in_homestretch_moves(self, standard_board_setup: BoardSetup):
        """Stack stack_1_2 (height=2) at HOMESTRETCH progress=51.
        Roll=4, effective=4/2=2. New progress=53. State stays HOMESTRETCH."""
        player1_stacks = [
            create_stack("stack_1_2", StackState.HOMESTRETCH, 2, 51),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1_2",
            roll=4,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_1_ID)
        stack = next(s for s in updated_player.stacks if s.stack_id == "stack_1_2")
        assert stack.progress == 53  # 51 + 4/2 = 53
        assert stack.state == StackState.HOMESTRETCH

        # Verify StackMoved event
        moved = next((e for e in result.events if isinstance(e, StackMoved)), None)
        assert moved is not None
        assert moved.from_progress == 51
        assert moved.to_progress == 53
        assert moved.from_state == StackState.HOMESTRETCH
        assert moved.to_state == StackState.HOMESTRETCH


# ===========================================================================
# 4. Homestretch Privacy
# ===========================================================================


class TestHomestretchPrivacy:
    """Test that homestretch is private -- no opponent collisions."""

    def test_no_opponent_collision_on_homestretch(self, standard_board_setup: BoardSetup):
        """Two players each have a stack in HOMESTRETCH at the same progress.
        detect_collisions should return an empty list because it only checks
        ROAD stacks."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        player2_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(
            player1_stacks, standard_board_setup, player2_stacks=player2_stacks
        )

        moving_player = next(p for p in state.players if p.player_id == PLAYER_1_ID)
        moved_piece = next(s for s in moving_player.stacks if s.stack_id == "stack_1")

        collisions = detect_collisions(state, moved_piece, moving_player, standard_board_setup)

        assert collisions == []


# ===========================================================================
# 5. Win Condition
# ===========================================================================


class TestWinCondition:
    """Test check_win_condition for various stack configurations."""

    def test_win_when_all_stacks_in_heaven(self, standard_board_setup: BoardSetup):
        """Player with all 4 stacks in HEAVEN should trigger win."""
        player1_stacks = [
            create_stack("stack_1", StackState.HEAVEN, 1, 55),
            create_stack("stack_2", StackState.HEAVEN, 1, 55),
            create_stack("stack_3", StackState.HEAVEN, 1, 55),
            create_stack("stack_4", StackState.HEAVEN, 1, 55),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        winner = check_win_condition(state)
        assert winner == PLAYER_1_ID

    def test_no_win_when_some_on_road(self, standard_board_setup: BoardSetup):
        """Player with 3 stacks HEAVEN + 1 ROAD should NOT win."""
        player1_stacks = [
            create_stack("stack_1", StackState.HEAVEN, 1, 55),
            create_stack("stack_2", StackState.HEAVEN, 1, 55),
            create_stack("stack_3", StackState.HEAVEN, 1, 55),
            create_stack("stack_4", StackState.ROAD, 1, 30),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        winner = check_win_condition(state)
        assert winner is None

    def test_no_win_when_merged_stack_not_in_heaven(self, standard_board_setup: BoardSetup):
        """Player with stack_1_2_3 in HEAVEN (height=3) and stack_4 on ROAD.
        Not all stacks are in HEAVEN, so no win."""
        player1_stacks = [
            create_stack("stack_1_2_3", StackState.HEAVEN, 3, 55),
            create_stack("stack_4", StackState.ROAD, 1, 20),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        winner = check_win_condition(state)
        assert winner is None
