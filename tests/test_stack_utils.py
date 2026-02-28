"""Tests for stack utility functions.

Tests the composition-based stack ID system:
- parse_components: extract component numbers from stack IDs
- build_stack_id: construct stack IDs from component numbers (sorted ascending)
- get_split_result: determine remaining and moving stack IDs after a split
- find_parent_stack: find existing stack whose components are a strict superset
"""

import importlib
import sys
from uuid import UUID

from app.schemas.game_engine import Player, Stack, StackState

# Load stack_utils directly to avoid triggering the engine __init__.py
# import chain (which references types being migrated in other tasks).
_spec = importlib.util.spec_from_file_location(
    "app.services.game.engine.stack_utils",
    "app/services/game/engine/stack_utils.py",
)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

parse_components = _module.parse_components
build_stack_id = _module.build_stack_id
get_split_result = _module.get_split_result
find_parent_stack = _module.find_parent_stack

PLAYER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_player(stacks: list[Stack]) -> Player:
    """Helper to create a Player with the given stacks."""
    return Player(
        player_id=PLAYER_ID,
        name="Test Player",
        color="red",
        stacks=stacks,
        turn_order=1,
        abs_starting_index=0,
    )


class TestParseComponents:
    """Test parse_components extracts component numbers from stack IDs."""

    def test_single_component(self):
        assert parse_components("stack_1") == [1]

    def test_two_components(self):
        assert parse_components("stack_1_2") == [1, 2]

    def test_four_components(self):
        assert parse_components("stack_1_2_3_4") == [1, 2, 3, 4]

    def test_non_sequential_components(self):
        assert parse_components("stack_2_4") == [2, 4]


class TestBuildStackId:
    """Test build_stack_id constructs stack IDs from component numbers."""

    def test_single_component(self):
        assert build_stack_id([1]) == "stack_1"

    def test_sorts_ascending(self):
        assert build_stack_id([3, 1, 2]) == "stack_1_2_3"

    def test_two_components(self):
        assert build_stack_id([2, 4]) == "stack_2_4"


class TestGetSplitResult:
    """Test get_split_result returns (remaining_id, moving_id) after a split."""

    def test_split_one_from_three(self):
        remaining, moving = get_split_result("stack_1_2_3", "stack_3")
        assert remaining == "stack_1_2"
        assert moving == "stack_3"

    def test_split_two_from_three(self):
        remaining, moving = get_split_result("stack_1_2_3", "stack_2_3")
        assert remaining == "stack_1"
        assert moving == "stack_2_3"

    def test_split_two_from_four(self):
        remaining, moving = get_split_result("stack_1_2_3_4", "stack_3_4")
        assert remaining == "stack_1_2"
        assert moving == "stack_3_4"


class TestFindParentStack:
    """Test find_parent_stack locates a stack whose components are a strict superset."""

    def test_finds_parent_for_partial_move(self):
        stack = Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10)
        player = _make_player([stack])
        result = find_parent_stack(player, "stack_2_3")
        assert result is not None
        assert result.stack_id == "stack_1_2_3"

    def test_returns_none_for_exact_match(self):
        stack = Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10)
        player = _make_player([stack])
        result = find_parent_stack(player, "stack_1_2_3")
        assert result is None

    def test_returns_none_when_no_parent_exists(self):
        stack = Stack(stack_id="stack_1_2", state=StackState.ROAD, height=2, progress=10)
        player = _make_player([stack])
        result = find_parent_stack(player, "stack_3_4")
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests for captures.py functions that use stack_utils
# ---------------------------------------------------------------------------
# Load captures module directly (avoiding broken __init__.py import chain).
# We need to pre-register the engine package and its sub-modules so that
# relative imports inside captures.py resolve without triggering __init__.py.
import types as _types

if "app.services.game.engine" not in sys.modules:
    _pkg = _types.ModuleType("app.services.game.engine")
    _pkg.__path__ = ["app/services/game/engine"]
    _pkg.__package__ = "app.services.game.engine"
    sys.modules["app.services.game.engine"] = _pkg

# events.py (imported by captures.py via relative import)
if "app.services.game.engine.events" not in sys.modules:
    _events_spec = importlib.util.spec_from_file_location(
        "app.services.game.engine.events",
        "app/services/game/engine/events.py",
    )
    _events_mod = importlib.util.module_from_spec(_events_spec)
    sys.modules[_events_spec.name] = _events_mod
    _events_spec.loader.exec_module(_events_mod)

# captures.py
_captures_spec = importlib.util.spec_from_file_location(
    "app.services.game.engine.captures",
    "app/services/game/engine/captures.py",
)
_captures_mod = importlib.util.module_from_spec(_captures_spec)
sys.modules[_captures_spec.name] = _captures_mod
_captures_spec.loader.exec_module(_captures_mod)

resolve_stacking = _captures_mod.resolve_stacking
send_to_hell = _captures_mod.send_to_hell

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Turn,
)

PLAYER_2_ID = UUID("00000000-0000-0000-0000-000000000002")


def _make_game_state(players: list[Player]) -> GameState:
    """Helper to create a minimal GameState for integration tests."""
    board_setup = BoardSetup(
        squares_to_win=57,
        squares_to_homestretch=52,
        starting_positions=[0, 13, 26, 39],
        safe_spaces=[0, 13, 26, 39],
        get_out_rolls=[6],
    )
    turn = Turn(
        player_id=players[0].player_id,
        initial_roll=True,
        rolls_to_allocate=[],
        legal_moves=[],
        current_turn_order=1,
        extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=players,
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=board_setup,
        current_turn=turn,
    )


class TestResolveStackingIntegration:
    """Integration tests for resolve_stacking using stack_utils-based IDs."""

    def test_merge_produces_sorted_id(self):
        """Merging stack_3 and stack_1 should produce stack_1_3 (sorted ascending)."""
        stack_3 = Stack(stack_id="stack_3", state=StackState.ROAD, height=1, progress=10)
        stack_1 = Stack(stack_id="stack_1", state=StackState.ROAD, height=1, progress=10)
        player = _make_player([stack_3, stack_1])
        state = _make_game_state([player])

        result = resolve_stacking(state, player, stack_3, stack_1)

        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        # Should have exactly one merged stack
        assert len(updated_player.stacks) == 1
        merged = updated_player.stacks[0]
        assert merged.stack_id == "stack_1_3"
        assert merged.height == 2


class TestSendToHellIntegration:
    """Integration tests for send_to_hell using stack_utils-based decomposition."""

    def test_decompose_composite_stack(self):
        """Capturing stack_1_2_3 should decompose into stack_1, stack_2, stack_3 in HELL."""
        composite = Stack(
            stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10
        )
        existing_hell = Stack(
            stack_id="stack_4", state=StackState.HELL, height=1, progress=0
        )
        player = _make_player([composite, existing_hell])
        state = _make_game_state([player])

        updated_state = send_to_hell(state, player, composite)

        updated_player = next(
            p for p in updated_state.players if p.player_id == PLAYER_ID
        )
        stacks_by_id = {s.stack_id: s for s in updated_player.stacks}

        # Should have 4 stacks: stack_1, stack_2, stack_3 (decomposed) + stack_4 (unchanged)
        assert len(stacks_by_id) == 4
        assert set(stacks_by_id.keys()) == {"stack_1", "stack_2", "stack_3", "stack_4"}

        # Decomposed stacks should be in HELL with height=1, progress=0
        for c in [1, 2, 3]:
            s = stacks_by_id[f"stack_{c}"]
            assert s.state == StackState.HELL
            assert s.height == 1
            assert s.progress == 0

        # Existing stack_4 should be unchanged
        assert stacks_by_id["stack_4"].state == StackState.HELL
        assert stacks_by_id["stack_4"].progress == 0


class TestLegalMoveGroup:
    def test_legal_move_group_creation(self):
        from app.schemas.game_engine import LegalMoveGroup
        group = LegalMoveGroup(stack_id="stack_1_2_3", moves=["stack_1_2_3", "stack_2_3", "stack_3"])
        assert group.stack_id == "stack_1_2_3"
        assert len(group.moves) == 3
