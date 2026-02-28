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


class TestMoveActionField:
    def test_move_action_has_stack_id(self):
        from app.services.game.engine.actions import MoveAction
        action = MoveAction(stack_id="stack_1_2")
        assert action.stack_id == "stack_1_2"
        assert action.action_type == "move"


# ---------------------------------------------------------------------------
# Load legal_moves module directly (avoiding broken __init__.py import chain).
# ---------------------------------------------------------------------------
if "app.services.game.engine.legal_moves" not in sys.modules:
    _legal_spec = importlib.util.spec_from_file_location(
        "app.services.game.engine.legal_moves",
        "app/services/game/engine/legal_moves.py",
    )
    _legal_mod = importlib.util.module_from_spec(_legal_spec)
    sys.modules[_legal_spec.name] = _legal_mod
    _legal_spec.loader.exec_module(_legal_mod)


class TestLegalMovesSubStackIds:
    def test_partial_moves_use_sub_stack_ids(self):
        from app.services.game.engine.legal_moves import get_legal_moves
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10)],
        )
        board = BoardSetup(squares_to_win=57, squares_to_homestretch=52,
                          starting_positions=[0], safe_spaces=[], get_out_rolls=[6])
        moves = get_legal_moves(player, 6, board)
        assert "stack_1_2_3" in moves  # full: 6%3==0, eff=2
        assert "stack_2_3" in moves    # partial 2: 6%2==0, eff=3
        assert "stack_3" in moves      # partial 1: 6%1==0, eff=6
        assert not any(":" in m for m in moves)

    def test_hell_stacks_on_get_out_roll(self):
        from app.services.game.engine.legal_moves import get_legal_moves
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0)],
        )
        board = BoardSetup(squares_to_win=57, squares_to_homestretch=52,
                          starting_positions=[0], safe_spaces=[], get_out_rolls=[6])
        moves = get_legal_moves(player, 6, board)
        assert "stack_4" in moves


class TestGetLegalMoveGroups:
    def test_groups_by_parent(self):
        from app.services.game.engine.legal_moves import get_legal_move_groups
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10),
                Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
            ],
        )
        board = BoardSetup(squares_to_win=57, squares_to_homestretch=52,
                          starting_positions=[0], safe_spaces=[], get_out_rolls=[6])
        groups = get_legal_move_groups(player, 6, board)
        assert len(groups) == 2
        stack_group = next(g for g in groups if g.stack_id == "stack_1_2_3")
        assert "stack_1_2_3" in stack_group.moves
        assert "stack_2_3" in stack_group.moves
        assert "stack_3" in stack_group.moves
        hell_group = next(g for g in groups if g.stack_id == "stack_4")
        assert hell_group.moves == ["stack_4"]


# ---------------------------------------------------------------------------
# Load start_game module directly (avoiding broken __init__.py import chain).
# ---------------------------------------------------------------------------
if "app.services.game" not in sys.modules:
    _game_pkg = _types.ModuleType("app.services.game")
    _game_pkg.__path__ = ["app/services/game"]
    _game_pkg.__package__ = "app.services.game"
    sys.modules["app.services.game"] = _game_pkg

if "app.services.game.start_game" not in sys.modules:
    _start_spec = importlib.util.spec_from_file_location(
        "app.services.game.start_game",
        "app/services/game/start_game.py",
    )
    _start_mod = importlib.util.module_from_spec(_start_spec)
    sys.modules[_start_spec.name] = _start_mod
    _start_spec.loader.exec_module(_start_mod)


# ---------------------------------------------------------------------------
# Load movement module directly (avoiding broken __init__.py import chain).
# We need to register all modules that movement.py imports via relative imports.
# ---------------------------------------------------------------------------

# actions.py (imported by validation.py)
if "app.services.game.engine.actions" not in sys.modules:
    _actions_spec = importlib.util.spec_from_file_location(
        "app.services.game.engine.actions",
        "app/services/game/engine/actions.py",
    )
    _actions_mod = importlib.util.module_from_spec(_actions_spec)
    sys.modules[_actions_spec.name] = _actions_mod
    _actions_spec.loader.exec_module(_actions_mod)

# validation.py (imported by movement.py)
if "app.services.game.engine.validation" not in sys.modules:
    _validation_spec = importlib.util.spec_from_file_location(
        "app.services.game.engine.validation",
        "app/services/game/engine/validation.py",
    )
    _validation_mod = importlib.util.module_from_spec(_validation_spec)
    sys.modules[_validation_spec.name] = _validation_mod
    _validation_spec.loader.exec_module(_validation_mod)

# rolling.py (imported by movement.py)
if "app.services.game.engine.rolling" not in sys.modules:
    _rolling_spec = importlib.util.spec_from_file_location(
        "app.services.game.engine.rolling",
        "app/services/game/engine/rolling.py",
    )
    _rolling_mod = importlib.util.module_from_spec(_rolling_spec)
    sys.modules[_rolling_spec.name] = _rolling_mod
    _rolling_spec.loader.exec_module(_rolling_mod)

# movement.py — always reload to ensure we have the current version
_movement_spec = importlib.util.spec_from_file_location(
    "app.services.game.engine.movement",
    "app/services/game/engine/movement.py",
)
_movement_mod = importlib.util.module_from_spec(_movement_spec)
sys.modules[_movement_spec.name] = _movement_mod
_movement_spec.loader.exec_module(_movement_mod)

apply_stack_move = _movement_mod.apply_stack_move
apply_split_move = _movement_mod.apply_split_move


def _make_movement_game_state(
    players: list[Player],
    rolls_to_allocate: list[int] | None = None,
) -> GameState:
    """Helper to create a GameState suitable for movement tests.

    Sets the turn to player 1 with the given rolls_to_allocate.
    """
    board_setup = BoardSetup(
        squares_to_win=57,
        squares_to_homestretch=52,
        starting_positions=[0, 13, 26, 39],
        safe_spaces=[0, 13, 26, 39],
        get_out_rolls=[6],
    )
    turn = Turn(
        player_id=players[0].player_id,
        initial_roll=False,
        rolls_to_allocate=rolls_to_allocate or [],
        legal_moves=[],
        current_turn_order=1,
        extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=players,
        current_event=CurrentEvent.PLAYER_CHOICE,
        board_setup=board_setup,
        current_turn=turn,
    )


class TestApplyStackMove:
    """Tests for apply_stack_move covering height=1 and multi-height stacks."""

    def test_height_1_move_on_road(self):
        """stack_1 at ROAD progress=10, roll=4 -> progress=14."""
        stack = Stack(stack_id="stack_1", state=StackState.ROAD, height=1, progress=10)
        player = _make_player([stack])
        state = _make_movement_game_state([player], rolls_to_allocate=[4])

        result = apply_stack_move(state, "stack_1", 4, player, state.board_setup)

        assert result.success
        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert moved.progress == 14
        assert moved.state == StackState.ROAD

        # Should have a StackMoved event
        from app.services.game.engine.events import StackMoved
        stack_moved = [e for e in result.events if isinstance(e, StackMoved)]
        assert len(stack_moved) == 1
        assert stack_moved[0].from_progress == 10
        assert stack_moved[0].to_progress == 14
        assert stack_moved[0].roll_used == 4

    def test_height_1_exit_hell(self):
        """stack_1 at HELL, roll=6 -> ROAD progress=0."""
        stack = Stack(stack_id="stack_1", state=StackState.HELL, height=1, progress=0)
        player = _make_player([stack])
        state = _make_movement_game_state([player], rolls_to_allocate=[6])

        result = apply_stack_move(state, "stack_1", 6, player, state.board_setup)

        assert result.success
        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert moved.progress == 0
        assert moved.state == StackState.ROAD

        # Should have a StackExitedHell event
        from app.services.game.engine.events import StackExitedHell
        exited = [e for e in result.events if isinstance(e, StackExitedHell)]
        assert len(exited) == 1
        assert exited[0].stack_id == "stack_1"
        assert exited[0].roll_used == 6

    def test_multi_height_effective_roll(self):
        """stack_1_2 at ROAD progress=10, height=2, roll=4 -> progress=12 (10+4/2)."""
        stack = Stack(stack_id="stack_1_2", state=StackState.ROAD, height=2, progress=10)
        player = _make_player([stack])
        state = _make_movement_game_state([player], rolls_to_allocate=[4])

        result = apply_stack_move(state, "stack_1_2", 4, player, state.board_setup)

        assert result.success
        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1_2")
        assert moved.progress == 12  # 10 + 4/2
        assert moved.state == StackState.ROAD

    def test_height_1_reaches_heaven(self):
        """stack_1 at ROAD progress=51, roll=6 -> HEAVEN (progress=57=squares_to_win)."""
        stack = Stack(stack_id="stack_1", state=StackState.ROAD, height=1, progress=51)
        player = _make_player([stack])
        state = _make_movement_game_state([player], rolls_to_allocate=[6])

        result = apply_stack_move(state, "stack_1", 6, player, state.board_setup)

        assert result.success
        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert moved.progress == 57
        assert moved.state == StackState.HEAVEN

        # Should have StackReachedHeaven event
        from app.services.game.engine.events import StackReachedHeaven
        heaven_events = [e for e in result.events if isinstance(e, StackReachedHeaven)]
        assert len(heaven_events) == 1
        assert heaven_events[0].stack_id == "stack_1"

    def test_invalid_roll_for_height(self):
        """Roll 5 for height=2 stack -> failure (5 % 2 != 0)."""
        stack = Stack(stack_id="stack_1_2", state=StackState.ROAD, height=2, progress=10)
        player = _make_player([stack])
        state = _make_movement_game_state([player], rolls_to_allocate=[5])

        result = apply_stack_move(state, "stack_1_2", 5, player, state.board_setup)

        assert not result.success
        assert result.error_code == "INVALID_STACK_ROLL"


class TestApplySplitMove:
    """Tests for apply_split_move: splitting a sub-stack off a parent."""

    def test_split_one_from_three(self):
        """stack_1_2_3 at ROAD progress=10, split stack_3, roll=6.
        remaining: stack_1_2 at progress=10, height=2
        moving: stack_3 at progress=16 (10+6/1), height=1
        """
        parent = Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10)
        player = _make_player([parent])
        state = _make_movement_game_state([player], rolls_to_allocate=[6])

        result = apply_split_move(
            state, parent, "stack_1_2", "stack_3", 6, player, state.board_setup
        )

        assert result.success
        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        stacks_by_id = {s.stack_id: s for s in updated_player.stacks}

        # Parent should be removed
        assert "stack_1_2_3" not in stacks_by_id

        # Remaining stack
        assert "stack_1_2" in stacks_by_id
        remaining = stacks_by_id["stack_1_2"]
        assert remaining.height == 2
        assert remaining.progress == 10
        assert remaining.state == StackState.ROAD

        # Moving stack
        assert "stack_3" in stacks_by_id
        moving = stacks_by_id["stack_3"]
        assert moving.height == 1
        assert moving.progress == 16  # 10 + 6/1
        assert moving.state == StackState.ROAD

        # Should have StackUpdate and StackMoved events
        from app.services.game.engine.events import StackUpdate, StackMoved
        updates = [e for e in result.events if isinstance(e, StackUpdate)]
        assert len(updates) == 1
        assert len(updates[0].remove_stacks) == 1
        assert updates[0].remove_stacks[0].stack_id == "stack_1_2_3"
        assert len(updates[0].add_stacks) == 2

        moved_events = [e for e in result.events if isinstance(e, StackMoved)]
        assert len(moved_events) == 1
        assert moved_events[0].stack_id == "stack_3"
        assert moved_events[0].from_progress == 10
        assert moved_events[0].to_progress == 16

    def test_split_two_from_three(self):
        """stack_1_2_3 at ROAD progress=10, split stack_2_3, roll=6.
        remaining: stack_1 at progress=10, height=1
        moving: stack_2_3 at progress=13 (10+6/2), height=2
        """
        parent = Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10)
        player = _make_player([parent])
        state = _make_movement_game_state([player], rolls_to_allocate=[6])

        result = apply_split_move(
            state, parent, "stack_1", "stack_2_3", 6, player, state.board_setup
        )

        assert result.success
        assert result.state is not None
        updated_player = next(
            p for p in result.state.players if p.player_id == PLAYER_ID
        )
        stacks_by_id = {s.stack_id: s for s in updated_player.stacks}

        assert "stack_1" in stacks_by_id
        assert stacks_by_id["stack_1"].height == 1
        assert stacks_by_id["stack_1"].progress == 10

        assert "stack_2_3" in stacks_by_id
        assert stacks_by_id["stack_2_3"].height == 2
        assert stacks_by_id["stack_2_3"].progress == 13  # 10 + 6/2

    def test_split_invalid_roll_for_moving_height(self):
        """Roll 5 for moving height=2 -> failure (5 % 2 != 0)."""
        parent = Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10)
        player = _make_player([parent])
        state = _make_movement_game_state([player], rolls_to_allocate=[5])

        result = apply_split_move(
            state, parent, "stack_1", "stack_2_3", 5, player, state.board_setup
        )

        assert not result.success
        assert result.error_code == "INVALID_SPLIT_ROLL"


class TestInitializeGame:
    def test_players_have_four_stacks_in_hell(self):
        from app.schemas.game_engine import GameSettings, PlayerAttributes, StackState
        from app.services.game.start_game import initialize_game
        settings = GameSettings(
            num_players=2,
            player_attributes=[
                PlayerAttributes(player_id=PLAYER_ID, name="P1", color="red"),
                PlayerAttributes(player_id=UUID("00000000-0000-0000-0000-000000000002"), name="P2", color="blue"),
            ],
            grid_length=7,
        )
        state = initialize_game(settings)
        for player in state.players:
            assert len(player.stacks) == 4
            for stack in player.stacks:
                assert stack.state == StackState.HELL
                assert stack.height == 1
                assert stack.progress == 0
            stack_ids = sorted(s.stack_id for s in player.stacks)
            assert stack_ids == ["stack_1", "stack_2", "stack_3", "stack_4"]


class TestCheckWinCondition:
    """Test check_win_condition uses Stack model."""

    def test_no_winner_when_stacks_not_in_heaven(self):
        from app.services.game.engine.process import check_win_condition
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1", state=StackState.HEAVEN, height=1, progress=57),
                Stack(stack_id="stack_2", state=StackState.ROAD, height=1, progress=10),
                Stack(stack_id="stack_3", state=StackState.HELL, height=1, progress=0),
                Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
            ],
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=BoardSetup(
                squares_to_win=57, squares_to_homestretch=52,
                starting_positions=[0], safe_spaces=[], get_out_rolls=[6],
            ),
        )
        assert check_win_condition(state) is None

    def test_winner_when_all_stacks_in_heaven(self):
        from app.services.game.engine.process import check_win_condition
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1", state=StackState.HEAVEN, height=1, progress=57),
                Stack(stack_id="stack_2", state=StackState.HEAVEN, height=1, progress=57),
                Stack(stack_id="stack_3", state=StackState.HEAVEN, height=1, progress=57),
                Stack(stack_id="stack_4", state=StackState.HEAVEN, height=1, progress=57),
            ],
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=BoardSetup(
                squares_to_win=57, squares_to_homestretch=52,
                starting_positions=[0], safe_spaces=[], get_out_rolls=[6],
            ),
        )
        assert check_win_condition(state) == PLAYER_ID

    def test_winner_with_merged_stacks_in_heaven(self):
        """Win with fewer stacks (some merged) all in heaven."""
        from app.services.game.engine.process import check_win_condition
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3_4", state=StackState.HEAVEN, height=4, progress=57),
            ],
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=BoardSetup(
                squares_to_win=57, squares_to_homestretch=52,
                starting_positions=[0], safe_spaces=[], get_out_rolls=[6],
            ),
        )
        assert check_win_condition(state) == PLAYER_ID
