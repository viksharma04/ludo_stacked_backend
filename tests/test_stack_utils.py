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
