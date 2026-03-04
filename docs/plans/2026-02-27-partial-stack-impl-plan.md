# Partial Stack Movement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the Token-to-Stack unified model transition with deterministic composition-based stack IDs, partial movement via sub-stack IDs, and grouped legal moves for frontend consumption.

**Architecture:** Pure functional game engine where all pieces are `Stack` objects with `stack_id`, `state`, `height`, `progress`. Stack IDs encode their composition (e.g., `stack_1_2_3`). Merges combine sorted components; splits peel off the largest. Legal moves use direct sub-stack IDs. `AwaitingChoice` events group moves by parent stack.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest, UV package manager

**Design doc:** `docs/plans/2026-02-27-partial-stack-design.md`

**Current state:** Schemas already migrated (Token/TokenState removed from `game_engine.py`). Tests and several engine modules still reference the old Token model and are currently broken. The `captures.py` and `legal_moves.py` files were partially updated but use patterns (`:count` format, `next_stack_index`) that conflict with the new design.

---

### Task 1: Create stack_utils.py

**Files:**
- Create: `app/services/game/engine/stack_utils.py`
- Create: `tests/test_stack_utils.py`

**Step 1: Write failing tests**

```python
# tests/test_stack_utils.py
"""Tests for stack ID utility functions."""

import pytest
from uuid import UUID

from app.schemas.game_engine import Player, Stack, StackState


class TestParseComponents:
    """Test parse_components extracts component numbers from stack IDs."""

    def test_single_component(self):
        from app.services.game.engine.stack_utils import parse_components
        assert parse_components("stack_1") == [1]

    def test_two_components(self):
        from app.services.game.engine.stack_utils import parse_components
        assert parse_components("stack_1_2") == [1, 2]

    def test_four_components(self):
        from app.services.game.engine.stack_utils import parse_components
        assert parse_components("stack_1_2_3_4") == [1, 2, 3, 4]

    def test_non_sequential_components(self):
        from app.services.game.engine.stack_utils import parse_components
        assert parse_components("stack_2_4") == [2, 4]


class TestBuildStackId:
    """Test build_stack_id creates sorted stack IDs from components."""

    def test_single_component(self):
        from app.services.game.engine.stack_utils import build_stack_id
        assert build_stack_id([1]) == "stack_1"

    def test_sorts_ascending(self):
        from app.services.game.engine.stack_utils import build_stack_id
        assert build_stack_id([3, 1, 2]) == "stack_1_2_3"

    def test_two_components(self):
        from app.services.game.engine.stack_utils import build_stack_id
        assert build_stack_id([2, 4]) == "stack_2_4"


class TestGetSplitResult:
    """Test get_split_result computes remaining and moving IDs."""

    def test_split_one_from_three(self):
        from app.services.game.engine.stack_utils import get_split_result
        remaining, moving = get_split_result("stack_1_2_3", "stack_3")
        assert remaining == "stack_1_2"
        assert moving == "stack_3"

    def test_split_two_from_three(self):
        from app.services.game.engine.stack_utils import get_split_result
        remaining, moving = get_split_result("stack_1_2_3", "stack_2_3")
        assert remaining == "stack_1"
        assert moving == "stack_2_3"

    def test_split_two_from_four(self):
        from app.services.game.engine.stack_utils import get_split_result
        remaining, moving = get_split_result("stack_1_2_3_4", "stack_3_4")
        assert remaining == "stack_1_2"
        assert moving == "stack_3_4"


PLAYER_ID = UUID("00000000-0000-0000-0000-000000000001")


class TestFindParentStack:
    """Test find_parent_stack locates stack containing move components."""

    def test_finds_parent_for_partial_move(self):
        from app.services.game.engine.stack_utils import find_parent_stack
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10),
                Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
            ],
        )
        parent = find_parent_stack(player, "stack_2_3")
        assert parent is not None
        assert parent.stack_id == "stack_1_2_3"

    def test_returns_none_for_exact_match(self):
        from app.services.game.engine.stack_utils import find_parent_stack
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10),
            ],
        )
        # Exact match is not a "parent" — it's the stack itself
        parent = find_parent_stack(player, "stack_1_2_3")
        assert parent is None

    def test_returns_none_when_no_parent(self):
        from app.services.game.engine.stack_utils import find_parent_stack
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2", state=StackState.ROAD, height=2, progress=10),
            ],
        )
        parent = find_parent_stack(player, "stack_3_4")
        assert parent is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stack_utils.py -v`
Expected: FAIL (module not found)

**Step 3: Implement stack_utils.py**

```python
# app/services/game/engine/stack_utils.py
"""Utility functions for composition-based stack IDs."""

from app.schemas.game_engine import Player, Stack


def parse_components(stack_id: str) -> list[int]:
    """Extract component numbers from a stack ID.

    "stack_1_2_3" -> [1, 2, 3]
    """
    parts = stack_id.split("_")
    return [int(p) for p in parts[1:]]


def build_stack_id(components: list[int]) -> str:
    """Build a stack ID from component numbers, sorted ascending.

    [3, 1, 2] -> "stack_1_2_3"
    """
    return "stack_" + "_".join(str(c) for c in sorted(components))


def get_split_result(parent_id: str, move_id: str) -> tuple[str, str]:
    """Compute remaining and moving IDs for a split.

    Returns (remaining_id, moving_id).
    """
    parent_components = set(parse_components(parent_id))
    move_components = set(parse_components(move_id))
    remaining_components = parent_components - move_components
    return build_stack_id(sorted(remaining_components)), move_id


def find_parent_stack(player: Player, move_id: str) -> Stack | None:
    """Find the existing stack whose components are a strict superset of move_id's components.

    Returns None if move_id exactly matches a stack (not a split) or no parent exists.
    """
    move_components = set(parse_components(move_id))
    for stack in player.stacks:
        stack_components = set(parse_components(stack.stack_id))
        if move_components < stack_components:  # strict subset
            return stack
    return None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stack_utils.py -v`
Expected: PASS (all 12 tests)

**Step 5: Commit**

```bash
git add app/services/game/engine/stack_utils.py tests/test_stack_utils.py
git commit -m "feat: add stack_utils module with composition-based ID utilities"
```

---

### Task 2: Update captures.py — resolve_stacking and send_to_hell

**Files:**
- Modify: `app/services/game/engine/captures.py:175-251` (resolve_stacking)
- Modify: `app/services/game/engine/captures.py:334-396` (send_to_hell)
- Test: `tests/test_stack_utils.py` (add integration tests)

**Step 1: Write failing tests for updated resolve_stacking**

Add to `tests/test_stack_utils.py`:

```python
class TestResolveStackingIntegration:
    """Test that resolve_stacking produces correct merged IDs."""

    def test_merge_produces_sorted_id(self):
        from app.schemas.game_engine import (
            BoardSetup, CurrentEvent, GamePhase, GameState, Stack, StackState, Turn,
        )
        from app.services.game.engine.captures import resolve_stacking

        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_3", state=StackState.ROAD, height=1, progress=10),
                Stack(stack_id="stack_1", state=StackState.ROAD, height=1, progress=10),
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

        result = resolve_stacking(state, player, player.stacks[0], player.stacks[1])
        assert result.state is not None

        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_ID)
        merged = next(s for s in updated_player.stacks if s.height == 2)
        assert merged.stack_id == "stack_1_3"  # sorted ascending
        assert merged.height == 2


class TestSendToHellIntegration:
    """Test that send_to_hell decomposes using component IDs."""

    def test_decompose_composite_stack(self):
        from app.schemas.game_engine import (
            BoardSetup, CurrentEvent, GamePhase, GameState, Stack, StackState,
        )
        from app.services.game.engine.captures import send_to_hell

        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10),
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

        new_state = send_to_hell(state, player, player.stacks[0])
        updated_player = next(p for p in new_state.players if p.player_id == PLAYER_ID)

        # Should have 4 stacks: stack_1, stack_2, stack_3 (decomposed) + stack_4 (unchanged)
        assert len(updated_player.stacks) == 4
        stack_ids = sorted(s.stack_id for s in updated_player.stacks)
        assert stack_ids == ["stack_1", "stack_2", "stack_3", "stack_4"]

        # All decomposed stacks should be in HELL
        for s in updated_player.stacks:
            if s.stack_id in ("stack_1", "stack_2", "stack_3"):
                assert s.state == StackState.HELL
                assert s.progress == 0
                assert s.height == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stack_utils.py::TestResolveStackingIntegration -v`
Run: `uv run pytest tests/test_stack_utils.py::TestSendToHellIntegration -v`
Expected: FAIL (wrong stack IDs / wrong decomposition)

**Step 3: Update resolve_stacking in captures.py**

Replace lines 175-251 of `captures.py`:

```python
def resolve_stacking(
    state: GameState,
    player: Player,
    piece1: Stack,
    piece2: Stack,
) -> CollisionResult:
    """Resolve a stacking situation (same player's stacks meet).

    Merges two stacks by combining their component numbers sorted ascending.
    e.g. stack_3 + stack_1 -> stack_1_3

    Args:
        state: Current game state.
        player: The player whose stacks are combining.
        piece1: First stack (the one that moved).
        piece2: Second stack (the stationary one).

    Returns:
        CollisionResult with updated state and StackUpdate event.
    """
    from .stack_utils import build_stack_id, parse_components

    events: list[AnyGameEvent] = []

    # Merge component numbers sorted ascending
    all_components = parse_components(piece1.stack_id) + parse_components(piece2.stack_id)
    new_stack_id = build_stack_id(all_components)
    new_height = len(all_components)

    logger.info(
        "Forming stack: new_id=%s, height=%d, from=%s+%s, player=%s",
        new_stack_id,
        new_height,
        piece1.stack_id,
        piece2.stack_id,
        str(player.player_id)[:8],
    )

    # Create the merged stack (keeps position/state of the stationary piece)
    new_stack = Stack(
        stack_id=new_stack_id,
        state=piece2.state,
        height=new_height,
        progress=piece2.progress,
    )

    # Remove the two old stacks, add the new one
    remaining_stacks = [
        s for s in player.stacks
        if s.stack_id not in (piece1.stack_id, piece2.stack_id)
    ]
    updated_stacks = [*remaining_stacks, new_stack]

    events.append(
        StackUpdate(
            player_id=player.player_id,
            add_stacks=[new_stack],
            remove_stacks=[piece1, piece2],
        )
    )

    updated_player = player.model_copy(update={"stacks": updated_stacks})
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    return CollisionResult(state=updated_state, events=events)
```

**Step 4: Update send_to_hell in captures.py**

Replace lines 334-396 of `captures.py`:

```python
def send_to_hell(
    state: GameState,
    player: Player,
    captured_stack: Stack,
) -> GameState:
    """Send a captured stack back to HELL.

    For height=1 stacks, resets the stack in place.
    For height>1 stacks, decomposes into individual component stacks in HELL.

    Args:
        state: Current game state.
        player: Player whose stack is being sent to HELL.
        captured_stack: The stack being captured.

    Returns:
        Updated game state.
    """
    from .stack_utils import parse_components

    logger.info(
        "Sending stack to hell: stack=%s (height=%d), player=%s",
        captured_stack.stack_id,
        captured_stack.height,
        str(player.player_id)[:8],
    )
    # Get fresh player from state
    current_player = next(p for p in state.players if p.player_id == player.player_id)

    if captured_stack.height == 1:
        # Simple: reset the stack to HELL in place
        updated_stacks = [
            s.model_copy(update={"state": StackState.HELL, "progress": 0})
            if s.stack_id == captured_stack.stack_id
            else s
            for s in current_player.stacks
        ]
        updated_player = current_player.model_copy(update={"stacks": updated_stacks})
    else:
        # Decompose composite stack into individual component stacks
        components = parse_components(captured_stack.stack_id)
        remaining_stacks = [
            s for s in current_player.stacks if s.stack_id != captured_stack.stack_id
        ]
        hell_stacks = [
            Stack(
                stack_id=f"stack_{c}",
                state=StackState.HELL,
                height=1,
                progress=0,
            )
            for c in components
        ]
        updated_player = current_player.model_copy(
            update={"stacks": [*remaining_stacks, *hell_stacks]}
        )

    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    return state.model_copy(update={"players": updated_players})
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_stack_utils.py -v`
Expected: PASS (all tests including integration)

**Step 6: Commit**

```bash
git add app/services/game/engine/captures.py tests/test_stack_utils.py
git commit -m "refactor: update captures to use composition-based stack IDs"
```

---

### Task 3: Update game_engine.py schemas

**Files:**
- Modify: `app/schemas/game_engine.py`

**Step 1: Write failing test for LegalMoveGroup**

Add to `tests/test_stack_utils.py`:

```python
class TestLegalMoveGroup:
    """Test the LegalMoveGroup schema."""

    def test_legal_move_group_creation(self):
        from app.schemas.game_engine import LegalMoveGroup
        group = LegalMoveGroup(
            stack_id="stack_1_2_3",
            moves=["stack_1_2_3", "stack_2_3", "stack_3"],
        )
        assert group.stack_id == "stack_1_2_3"
        assert len(group.moves) == 3
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stack_utils.py::TestLegalMoveGroup -v`
Expected: FAIL (ImportError: cannot import name 'LegalMoveGroup')

**Step 3: Update game_engine.py**

Changes to `app/schemas/game_engine.py`:

1. Add `LegalMoveGroup` after `Stack`:
```python
class LegalMoveGroup(BaseModel):
    stack_id: str
    moves: list[str]
```

2. Remove `next_stack_index` from `Player`:
```python
class Player(PlayerAttributes):
    stacks: list[Stack]
    turn_order: int
    abs_starting_index: int
    # next_stack_index: REMOVED
```

3. Remove `Move` model (lines 76-78) — unused after migration.

4. Remove `ActionLog` model (lines 98-101) — unused after migration.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stack_utils.py::TestLegalMoveGroup -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/schemas/game_engine.py tests/test_stack_utils.py
git commit -m "refactor: add LegalMoveGroup, remove next_stack_index from Player"
```

---

### Task 4: Update actions.py and validation.py

**Files:**
- Modify: `app/services/game/engine/actions.py:15-21`
- Modify: `app/services/game/engine/validation.py:191,194,199`

**Step 1: Write failing test**

Add to `tests/test_stack_utils.py`:

```python
class TestMoveActionField:
    """Test MoveAction uses stack_id field."""

    def test_move_action_has_stack_id(self):
        from app.services.game.engine.actions import MoveAction
        action = MoveAction(stack_id="stack_1_2")
        assert action.stack_id == "stack_1_2"
        assert action.action_type == "move"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stack_utils.py::TestMoveActionField -v`
Expected: FAIL (unexpected keyword argument 'stack_id')

**Step 3: Update actions.py**

In `app/services/game/engine/actions.py`, replace lines 15-21:

```python
class MoveAction(BaseModel):
    """Player selects a stack to move."""

    action_type: Literal["move"] = "move"
    stack_id: str = Field(
        ..., description="ID of the stack to move"
    )
```

**Step 4: Update validation.py**

In `app/services/game/engine/validation.py`, update three lines:

- Line 191: `action.token_or_stack_id` -> `action.stack_id`
- Line 194: `action.token_or_stack_id` -> `action.stack_id`
- Line 199: `action.token_or_stack_id` -> `action.stack_id`

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_stack_utils.py::TestMoveActionField -v`
Expected: PASS

**Step 6: Commit**

```bash
git add app/services/game/engine/actions.py app/services/game/engine/validation.py tests/test_stack_utils.py
git commit -m "refactor: rename MoveAction.token_or_stack_id to stack_id"
```

---

### Task 5: Update legal_moves.py — sub-stack IDs and get_legal_move_groups

**Files:**
- Modify: `app/services/game/engine/legal_moves.py`
- Test: `tests/test_stack_utils.py` (add legal moves tests)

**Step 1: Write failing tests**

Add to `tests/test_stack_utils.py`:

```python
class TestLegalMovesSubStackIds:
    """Test that legal_moves uses sub-stack IDs instead of :count format."""

    def test_partial_moves_use_sub_stack_ids(self):
        from app.services.game.engine.legal_moves import get_legal_moves

        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10),
            ],
        )
        board = BoardSetup(
            squares_to_win=57, squares_to_homestretch=52,
            starting_positions=[0], safe_spaces=[], get_out_rolls=[6],
        )

        moves = get_legal_moves(player, 6, board)
        # Full stack: 6 % 3 == 0, effective=2 -> 10+2=12 <= 57 -> legal
        assert "stack_1_2_3" in moves
        # Partial 2: 6 % 2 == 0, effective=3 -> 10+3=13 <= 57 -> legal (stack_2_3)
        assert "stack_2_3" in moves
        # Partial 1: 6 % 1 == 0, effective=6 -> 10+6=16 <= 57 -> legal (stack_3)
        assert "stack_3" in moves
        # No :count format
        assert not any(":" in m for m in moves)

    def test_hell_stacks_included_on_get_out_roll(self):
        from app.services.game.engine.legal_moves import get_legal_moves

        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
            ],
        )
        board = BoardSetup(
            squares_to_win=57, squares_to_homestretch=52,
            starting_positions=[0], safe_spaces=[], get_out_rolls=[6],
        )

        moves = get_legal_moves(player, 6, board)
        assert "stack_4" in moves


class TestGetLegalMoveGroups:
    """Test get_legal_move_groups groups by parent stack."""

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
        board = BoardSetup(
            squares_to_win=57, squares_to_homestretch=52,
            starting_positions=[0], safe_spaces=[], get_out_rolls=[6],
        )

        groups = get_legal_move_groups(player, 6, board)
        assert len(groups) == 2

        # Find the group for stack_1_2_3
        stack_group = next(g for g in groups if g.stack_id == "stack_1_2_3")
        assert "stack_1_2_3" in stack_group.moves
        assert "stack_2_3" in stack_group.moves
        assert "stack_3" in stack_group.moves

        # Find the group for stack_4
        hell_group = next(g for g in groups if g.stack_id == "stack_4")
        assert hell_group.moves == ["stack_4"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stack_utils.py::TestLegalMovesSubStackIds -v`
Run: `uv run pytest tests/test_stack_utils.py::TestGetLegalMoveGroups -v`
Expected: FAIL

**Step 3: Rewrite legal_moves.py**

```python
# app/services/game/engine/legal_moves.py
"""Legal move calculation for stacks."""

import logging

from app.schemas.game_engine import BoardSetup, LegalMoveGroup, Player, StackState

from .stack_utils import build_stack_id, parse_components

logger = logging.getLogger(__name__)


def get_legal_moves(player: Player, roll: int, board_setup: BoardSetup) -> list[str]:
    """Determine legal moves for a player given a roll.

    Returns stack IDs (including sub-stack IDs for partial moves).
    e.g. ["stack_1_2_3", "stack_2_3", "stack_3", "stack_4"]
    """
    logger.debug(
        "Calculating legal moves: player=%s, roll=%d",
        str(player.player_id)[:8],
        roll,
    )
    legal_moves: list[str] = []

    for stack in player.stacks:
        if stack.state == StackState.HELL and roll in board_setup.get_out_rolls:
            legal_moves.append(stack.stack_id)

        elif stack.state in (StackState.ROAD, StackState.HOMESTRETCH):
            # Full stack movement
            if roll % stack.height == 0:
                effective_roll = roll // stack.height
                if stack.progress + effective_roll <= board_setup.squares_to_win:
                    legal_moves.append(stack.stack_id)

            # Partial stack movements (only for multi-height stacks)
            if stack.height > 1:
                components = parse_components(stack.stack_id)
                for partial_count in range(1, stack.height):
                    if roll % partial_count == 0:
                        effective_roll = roll // partial_count
                        if stack.progress + effective_roll <= board_setup.squares_to_win:
                            # Build sub-stack ID from the largest components
                            moving_components = components[-partial_count:]
                            move_id = build_stack_id(moving_components)
                            legal_moves.append(move_id)

    logger.debug(
        "Legal moves calculated: player=%s, roll=%d, count=%d, moves=%s",
        str(player.player_id)[:8],
        roll,
        len(legal_moves),
        legal_moves,
    )
    return legal_moves


def get_legal_move_groups(
    player: Player, roll: int, board_setup: BoardSetup
) -> list[LegalMoveGroup]:
    """Get legal moves grouped by parent stack for frontend consumption."""
    flat_moves = get_legal_moves(player, roll, board_setup)

    # Group moves by their parent stack
    groups: dict[str, list[str]] = {}
    for move_id in flat_moves:
        # Check if this move is a sub-stack of an existing stack
        parent = None
        for stack in player.stacks:
            if move_id == stack.stack_id:
                parent = stack.stack_id
                break
            move_comps = set(parse_components(move_id))
            stack_comps = set(parse_components(stack.stack_id))
            if move_comps < stack_comps:
                parent = stack.stack_id
                break

        if parent is None:
            # Should not happen with valid legal moves, but handle gracefully
            parent = move_id

        if parent not in groups:
            groups[parent] = []
        groups[parent].append(move_id)

    return [
        LegalMoveGroup(stack_id=stack_id, moves=moves)
        for stack_id, moves in groups.items()
    ]


def has_any_legal_moves(player: Player, roll: int, board_setup: BoardSetup) -> bool:
    """Quick check if player has any legal moves."""
    for stack in player.stacks:
        if stack.state == StackState.HELL and roll in board_setup.get_out_rolls:
            return True

        if stack.state in (StackState.ROAD, StackState.HOMESTRETCH):
            if roll % stack.height == 0:
                effective_roll = roll // stack.height
                if stack.progress + effective_roll <= board_setup.squares_to_win:
                    return True

            if stack.height > 1:
                for partial_count in range(1, stack.height):
                    if roll % partial_count == 0:
                        effective_roll = roll // partial_count
                        if stack.progress + effective_roll <= board_setup.squares_to_win:
                            return True

    return False
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stack_utils.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/game/engine/legal_moves.py tests/test_stack_utils.py
git commit -m "refactor: legal moves use sub-stack IDs, add get_legal_move_groups"
```

---

### Task 6: Update start_game.py

**Files:**
- Modify: `app/services/game/start_game.py`

**Step 1: Write failing test**

Add to `tests/test_stack_utils.py`:

```python
class TestInitializeGame:
    """Test game initialization creates stacks instead of tokens."""

    def test_players_have_four_stacks_in_hell(self):
        from app.schemas.game_engine import GameSettings, PlayerAttributes, StackState
        from app.services.game.start_game import initialize_game

        settings = GameSettings(
            num_players=2,
            player_attributes=[
                PlayerAttributes(player_id=PLAYER_ID, name="P1", color="red"),
                PlayerAttributes(
                    player_id=UUID("00000000-0000-0000-0000-000000000002"),
                    name="P2", color="blue",
                ),
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
            # Stack IDs should be stack_1 through stack_4
            stack_ids = sorted(s.stack_id for s in player.stacks)
            assert stack_ids == ["stack_1", "stack_2", "stack_3", "stack_4"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stack_utils.py::TestInitializeGame -v`
Expected: FAIL

**Step 3: Update start_game.py**

Replace `_create_initial_tokens` with `_create_initial_stacks`, update `_initialize_players`:

```python
# app/services/game/start_game.py
from uuid import UUID

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameSettings,
    GameState,
    Player,
    Stack,
    StackState,
)


def validate_game_settings(game_settings: GameSettings) -> None:
    """Validate game settings before initializing a game."""
    if game_settings.num_players < 2:
        raise ValueError("A minimum of 2 players is required to start the game.")
    if game_settings.grid_length < 3:
        raise ValueError("Grid length must be at least 3.")
    if len(game_settings.player_attributes) != game_settings.num_players:
        raise ValueError("Number of player IDs must match the number of players.")

    player_ids: set[UUID] = set()
    player_names: set[str] = set()
    player_colors: set[str] = set()
    for player in game_settings.player_attributes:
        if player.player_id in player_ids:
            raise ValueError(f"Duplicate player ID found: {player.player_id}")
        if player.name in player_names:
            raise ValueError(f"Duplicate player name found: {player.name}")
        if player.color in player_colors:
            raise ValueError(f"Duplicate player color found: {player.color}")
        player_ids.add(player.player_id)
        player_names.add(player.name)
        player_colors.add(player.color)


def _create_board_setup(game_settings: GameSettings) -> BoardSetup:
    """Create board setup based on game settings."""
    grid_length = game_settings.grid_length
    num_players = game_settings.num_players

    starting_positions = [0] + [sum(2 * grid_length + 1 for _ in range(i + 1)) for i in range(3)]
    safe_spaces = []
    for pos in starting_positions:
        safe_spaces.append(pos)
        safe_spaces.append(pos + (2 * grid_length - 2))

    starting_positions = starting_positions[:num_players]

    return BoardSetup(
        squares_to_win=(9 * grid_length) + 1,
        squares_to_homestretch=8 * grid_length + 1,
        starting_positions=starting_positions,
        get_out_rolls=game_settings.get_out_rolls,
        safe_spaces=safe_spaces,
    )


def _create_initial_stacks() -> list[Stack]:
    """Create initial stacks for a player — 4 individual stacks in HELL."""
    return [
        Stack(
            stack_id=f"stack_{i}",
            state=StackState.HELL,
            height=1,
            progress=0,
        )
        for i in range(1, 5)
    ]


def _initialize_players(game_settings: GameSettings, starting_positions: list[int]) -> list[Player]:
    """Initialize players with deterministic turn order."""
    shuffled_attributes = list(game_settings.player_attributes)

    players = []
    for index, player_attr in enumerate(shuffled_attributes):
        player = Player(
            player_id=player_attr.player_id,
            name=player_attr.name,
            color=player_attr.color,
            turn_order=index + 1,
            abs_starting_index=starting_positions[index],
            stacks=_create_initial_stacks(),
        )
        players.append(player)

    return players


def initialize_game(game_settings: GameSettings) -> GameState:
    """Validate game settings and return an initialized GameState."""
    validate_game_settings(game_settings)

    board_setup = _create_board_setup(game_settings)
    players = _initialize_players(game_settings, board_setup.starting_positions)

    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=players,
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=board_setup,
        current_turn=None,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stack_utils.py::TestInitializeGame -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/game/start_game.py tests/test_stack_utils.py
git commit -m "refactor: start_game creates stack_1..4 instead of Token objects"
```

---

### Task 7: Rewrite movement.py

This is the largest task. The full rewrite replaces Token-based movement with Stack-only logic.

**Files:**
- Modify: `app/services/game/engine/movement.py` (full rewrite)
- Test: `tests/test_stack_utils.py` (add movement tests)

**Step 1: Write failing tests for apply_stack_move**

Add to `tests/test_stack_utils.py`:

```python
class TestApplyStackMove:
    """Test apply_stack_move for height-1 and multi-height stacks."""

    def _make_game(self, stacks_p1, stacks_p2=None):
        """Helper to build a game state."""
        p2_id = UUID("00000000-0000-0000-0000-000000000002")
        player1 = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0, stacks=stacks_p1,
        )
        player2 = Player(
            player_id=p2_id, name="P2", color="blue",
            turn_order=2, abs_starting_index=26,
            stacks=stacks_p2 or [
                Stack(stack_id=f"stack_{i}", state=StackState.HELL, height=1, progress=0)
                for i in range(1, 5)
            ],
        )
        board = BoardSetup(
            squares_to_win=57, squares_to_homestretch=52,
            starting_positions=[0, 26], safe_spaces=[0, 26], get_out_rolls=[6],
        )
        turn = Turn(
            player_id=PLAYER_ID, initial_roll=True,
            rolls_to_allocate=[4], legal_moves=["stack_1"],
            current_turn_order=1, extra_rolls=0,
        )
        return GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player1, player2],
            current_event=CurrentEvent.PLAYER_CHOICE,
            board_setup=board, current_turn=turn,
        )

    def test_height_1_move_on_road(self):
        from app.services.game.engine.movement import apply_stack_move
        stacks = [
            Stack(stack_id="stack_1", state=StackState.ROAD, height=1, progress=10),
            Stack(stack_id="stack_2", state=StackState.HELL, height=1, progress=0),
            Stack(stack_id="stack_3", state=StackState.HELL, height=1, progress=0),
            Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
        ]
        state = self._make_game(stacks)
        player = state.players[0]

        result = apply_stack_move(state, "stack_1", 4, player, state.board_setup)
        assert result.success

        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_ID)
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert moved.progress == 14  # 10 + 4
        assert moved.state == StackState.ROAD

    def test_height_1_exit_hell(self):
        from app.services.game.engine.movement import apply_stack_move
        stacks = [
            Stack(stack_id="stack_1", state=StackState.HELL, height=1, progress=0),
            Stack(stack_id="stack_2", state=StackState.HELL, height=1, progress=0),
            Stack(stack_id="stack_3", state=StackState.HELL, height=1, progress=0),
            Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
        ]
        state = self._make_game(stacks)
        player = state.players[0]

        result = apply_stack_move(state, "stack_1", 6, player, state.board_setup)
        assert result.success

        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_ID)
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1")
        assert moved.progress == 0
        assert moved.state == StackState.ROAD

    def test_multi_height_effective_roll(self):
        from app.services.game.engine.movement import apply_stack_move
        stacks = [
            Stack(stack_id="stack_1_2", state=StackState.ROAD, height=2, progress=10),
            Stack(stack_id="stack_3", state=StackState.HELL, height=1, progress=0),
            Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
        ]
        state = self._make_game(stacks)
        player = state.players[0]

        result = apply_stack_move(state, "stack_1_2", 4, player, state.board_setup)
        assert result.success

        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_ID)
        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_1_2")
        assert moved.progress == 12  # 10 + 4/2 = 12


class TestApplySplitMove:
    """Test apply_split_move for partial stack movements."""

    def test_split_one_from_three(self):
        from app.services.game.engine.movement import apply_split_move
        player = Player(
            player_id=PLAYER_ID, name="P1", color="red",
            turn_order=1, abs_starting_index=0,
            stacks=[
                Stack(stack_id="stack_1_2_3", state=StackState.ROAD, height=3, progress=10),
                Stack(stack_id="stack_4", state=StackState.HELL, height=1, progress=0),
            ],
        )
        p2_id = UUID("00000000-0000-0000-0000-000000000002")
        player2 = Player(
            player_id=p2_id, name="P2", color="blue",
            turn_order=2, abs_starting_index=26,
            stacks=[Stack(stack_id=f"stack_{i}", state=StackState.HELL, height=1, progress=0) for i in range(1, 5)],
        )
        board = BoardSetup(
            squares_to_win=57, squares_to_homestretch=52,
            starting_positions=[0, 26], safe_spaces=[0, 26], get_out_rolls=[6],
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[player, player2],
            current_event=CurrentEvent.PLAYER_CHOICE,
            board_setup=board,
            current_turn=Turn(
                player_id=PLAYER_ID, rolls_to_allocate=[6],
                legal_moves=["stack_3"], current_turn_order=1,
            ),
        )

        parent = player.stacks[0]
        result = apply_split_move(state, parent, "stack_1_2", "stack_3", 6, player, board)
        assert result.success

        updated_player = next(p for p in result.state.players if p.player_id == PLAYER_ID)
        stack_ids = sorted(s.stack_id for s in updated_player.stacks)
        assert "stack_1_2" in stack_ids   # remaining at progress 10
        assert "stack_3" in stack_ids     # moved to progress 16
        assert "stack_4" in stack_ids     # unchanged

        remaining = next(s for s in updated_player.stacks if s.stack_id == "stack_1_2")
        assert remaining.progress == 10
        assert remaining.height == 2

        moved = next(s for s in updated_player.stacks if s.stack_id == "stack_3")
        assert moved.progress == 16  # 10 + 6/1 = 16
        assert moved.height == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stack_utils.py::TestApplyStackMove -v`
Run: `uv run pytest tests/test_stack_utils.py::TestApplySplitMove -v`
Expected: FAIL

**Step 3: Rewrite movement.py**

```python
# app/services/game/engine/movement.py
"""Stack movement logic."""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GameState,
    Player,
    Stack,
    StackState,
    Turn,
)

from .captures import detect_collisions, resolve_collision
from .events import (
    AnyGameEvent,
    AwaitingChoice,
    RollGranted,
    StackExitedHell,
    StackMoved,
    StackReachedHeaven,
    StackUpdate,
    TurnEnded,
    TurnStarted,
)
from .legal_moves import get_legal_moves
from .rolling import create_new_turn, get_next_turn_order
from .stack_utils import find_parent_stack, get_split_result
from .validation import ProcessResult


def process_move(state: GameState, stack_id: str, player_id: UUID) -> ProcessResult:
    """Process a player's move selection.

    Resolves whether the move is a full stack move or a split move
    by checking if stack_id matches an existing stack or is a subset
    of a parent stack's components.
    """
    current_turn = state.current_turn
    if current_turn is None:
        return ProcessResult.failure("NO_ACTIVE_TURN", "No active turn")

    if not current_turn.rolls_to_allocate:
        return ProcessResult.failure("NO_ROLLS", "No rolls to allocate")

    roll = current_turn.rolls_to_allocate[0]
    current_player = next(p for p in state.players if p.player_id == current_turn.player_id)

    logger.info(
        "Processing move: player=%s, stack_id=%s, roll=%d",
        str(player_id)[:8], stack_id, roll,
    )

    # Check for exact match (full stack move)
    exact_stack = next((s for s in current_player.stacks if s.stack_id == stack_id), None)
    if exact_stack is not None:
        result = apply_stack_move(state, stack_id, roll, current_player, state.board_setup)
    else:
        # Parent lookup — this is a split move
        parent = find_parent_stack(current_player, stack_id)
        if parent is None:
            return ProcessResult.failure(
                "STACK_NOT_FOUND", f"No stack found for move ID {stack_id}"
            )
        remaining_id, moving_id = get_split_result(parent.stack_id, stack_id)
        result = apply_split_move(
            state, parent, remaining_id, moving_id, roll,
            current_player, state.board_setup,
        )

    if not result.success:
        return result

    if result.state is None:
        return ProcessResult.failure("STATE_LOST", "State lost during move processing")

    return process_after_move(result.state, result.events, current_turn, roll)


def apply_stack_move(
    state: GameState,
    stack_id: str,
    roll: int,
    player: Player,
    board_setup: BoardSetup,
) -> ProcessResult:
    """Apply movement to a stack (any height, including 1).

    Handles exit from HELL, movement on ROAD/HOMESTRETCH, reaching HEAVEN.
    """
    events: list[AnyGameEvent] = []

    stack = next((s for s in player.stacks if s.stack_id == stack_id), None)
    if stack is None:
        return ProcessResult.failure("STACK_NOT_FOUND", f"Stack {stack_id} not found")

    old_state = stack.state
    old_progress = stack.progress

    if stack.state == StackState.HELL:
        if roll not in board_setup.get_out_rolls:
            return ProcessResult.failure(
                "INVALID_GET_OUT_ROLL", f"Roll {roll} is not a valid get-out roll"
            )
        new_stack_state = StackState.ROAD
        new_progress = 0
        events.append(
            StackExitedHell(player_id=player.player_id, stack_id=stack_id, roll_used=roll)
        )
    elif stack.state in (StackState.ROAD, StackState.HOMESTRETCH):
        if roll % stack.height != 0:
            return ProcessResult.failure(
                "INVALID_STACK_ROLL",
                f"Roll {roll} not divisible by stack height {stack.height}",
            )
        effective_roll = roll // stack.height
        new_progress = stack.progress + effective_roll

        if new_progress > board_setup.squares_to_win:
            return ProcessResult.failure("MOVE_EXCEEDS_BOARD", "Move would exceed board bounds")

        if new_progress == board_setup.squares_to_win:
            new_stack_state = StackState.HEAVEN
            events.append(StackReachedHeaven(player_id=player.player_id, stack_id=stack_id))
        elif new_progress >= board_setup.squares_to_homestretch:
            new_stack_state = StackState.HOMESTRETCH
        else:
            new_stack_state = stack.state

        events.append(
            StackMoved(
                player_id=player.player_id,
                stack_id=stack_id,
                from_state=old_state,
                to_state=new_stack_state,
                from_progress=old_progress,
                to_progress=new_progress,
                roll_used=roll,
            )
        )
    else:
        return ProcessResult.failure("INVALID_STATE", f"Cannot move stack in state {stack.state}")

    # Update the stack in player's stacks list
    updated_stack = stack.model_copy(
        update={"state": new_stack_state, "progress": new_progress}
    )
    updated_stacks = [
        updated_stack if s.stack_id == stack_id else s for s in player.stacks
    ]
    updated_player = player.model_copy(update={"stacks": updated_stacks})
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    # Handle collisions on ROAD
    if new_stack_state == StackState.ROAD:
        collision_result = handle_road_collision(
            updated_state, updated_stack, updated_player, board_setup, events
        )
        if collision_result is not None:
            return collision_result

    return ProcessResult.ok(updated_state, events)


def apply_split_move(
    state: GameState,
    parent: Stack,
    remaining_id: str,
    moving_id: str,
    roll: int,
    player: Player,
    board_setup: BoardSetup,
) -> ProcessResult:
    """Split a stack and move part of it.

    The parent stack is replaced by a remaining stack (stays in place)
    and a moving stack (advances by effective_roll).
    """
    from .stack_utils import parse_components

    events: list[AnyGameEvent] = []

    moving_height = len(parse_components(moving_id))
    remaining_height = len(parse_components(remaining_id))

    if roll % moving_height != 0:
        return ProcessResult.failure(
            "INVALID_PARTIAL_ROLL",
            f"Roll {roll} not divisible by moving height {moving_height}",
        )

    effective_roll = roll // moving_height
    new_progress = parent.progress + effective_roll

    if new_progress > board_setup.squares_to_win:
        return ProcessResult.failure("MOVE_EXCEEDS_BOARD", "Move would exceed board bounds")

    # Determine state for moving stack
    if new_progress == board_setup.squares_to_win:
        moving_state = StackState.HEAVEN
    elif new_progress >= board_setup.squares_to_homestretch:
        moving_state = StackState.HOMESTRETCH
    else:
        moving_state = parent.state

    # Create remaining and moving stacks
    remaining_stack = Stack(
        stack_id=remaining_id,
        state=parent.state,
        height=remaining_height,
        progress=parent.progress,
    )
    moving_stack = Stack(
        stack_id=moving_id,
        state=moving_state,
        height=moving_height,
        progress=new_progress,
    )

    # Emit StackUpdate for the split
    events.append(
        StackUpdate(
            player_id=player.player_id,
            remove_stacks=[parent],
            add_stacks=[remaining_stack, moving_stack],
        )
    )

    # Emit movement event
    events.append(
        StackMoved(
            player_id=player.player_id,
            stack_id=moving_id,
            from_state=parent.state,
            to_state=moving_state,
            from_progress=parent.progress,
            to_progress=new_progress,
            roll_used=roll,
        )
    )

    if moving_state == StackState.HEAVEN:
        events.append(StackReachedHeaven(player_id=player.player_id, stack_id=moving_id))

    # Update player's stacks: remove parent, add remaining + moving
    updated_stacks = [s for s in player.stacks if s.stack_id != parent.stack_id]
    updated_stacks.extend([remaining_stack, moving_stack])

    updated_player = player.model_copy(update={"stacks": updated_stacks})
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    # Handle collisions on ROAD
    if moving_state == StackState.ROAD:
        # Get fresh player from updated state
        fresh_player = next(p for p in updated_state.players if p.player_id == player.player_id)
        collision_result = handle_road_collision(
            updated_state, moving_stack, fresh_player, board_setup, events
        )
        if collision_result is not None:
            return collision_result

    return ProcessResult.ok(updated_state, events)


def process_after_move(
    state: GameState,
    events: list[AnyGameEvent],
    original_turn: Turn,
    used_roll: int,
) -> ProcessResult:
    """Handle post-move logic: remaining rolls, extra rolls, or turn end."""
    current_turn = state.current_turn
    if current_turn is None:
        return ProcessResult.failure("NO_ACTIVE_TURN", "Turn lost during move")

    remaining_rolls = original_turn.rolls_to_allocate[1:]
    updated_player = next(p for p in state.players if p.player_id == original_turn.player_id)

    # Check for remaining rolls
    if remaining_rolls:
        legal_moves = get_legal_moves(updated_player, remaining_rolls[0], state.board_setup)

        if legal_moves:
            updated_turn = current_turn.model_copy(
                update={
                    "rolls_to_allocate": remaining_rolls,
                    "legal_moves": legal_moves,
                }
            )
            events.append(
                AwaitingChoice(
                    player_id=original_turn.player_id,
                    legal_moves=legal_moves,
                    roll_to_allocate=remaining_rolls[0],
                )
            )
            new_state = state.model_copy(
                update={
                    "current_event": CurrentEvent.PLAYER_CHOICE,
                    "current_turn": updated_turn,
                }
            )
            return ProcessResult.ok(new_state, events)

        remaining_rolls = []

    # Check for extra rolls from captures
    if current_turn.extra_rolls > 0:
        events.append(RollGranted(player_id=original_turn.player_id, reason="capture_bonus"))
        updated_turn = current_turn.model_copy(
            update={
                "rolls_to_allocate": remaining_rolls,
                "extra_rolls": current_turn.extra_rolls - 1,
                "legal_moves": [],
            }
        )
        new_state = state.model_copy(
            update={
                "current_event": CurrentEvent.PLAYER_ROLL,
                "current_turn": updated_turn,
            }
        )
        return ProcessResult.ok(new_state, events)

    # End turn
    next_turn_order = get_next_turn_order(original_turn.current_turn_order, len(state.players))
    next_player = next(p for p in state.players if p.turn_order == next_turn_order)

    events.append(
        TurnEnded(
            player_id=original_turn.player_id,
            reason="all_rolls_used",
            next_player_id=next_player.player_id,
        )
    )
    events.append(TurnStarted(player_id=next_player.player_id, turn_number=next_turn_order))
    events.append(RollGranted(player_id=next_player.player_id, reason="turn_start"))

    new_turn = create_new_turn(turn_order=next_turn_order, players=state.players)
    new_state = state.model_copy(
        update={
            "current_event": CurrentEvent.PLAYER_ROLL,
            "current_turn": new_turn,
        }
    )
    return ProcessResult.ok(new_state, events)


def handle_road_collision(
    state: GameState,
    moved_piece: Stack,
    player: Player,
    board_setup: BoardSetup,
    events: list[AnyGameEvent],
) -> ProcessResult | None:
    """Check for and handle collisions after a move on the ROAD."""
    collisions = detect_collisions(state, moved_piece, player, board_setup)

    if not collisions:
        return None

    for other_player, other_piece in collisions:
        collision_result = resolve_collision(
            state, player, moved_piece, other_player, other_piece, events
        )
        if collision_result.state is not None:
            state = collision_result.state
        events.extend(collision_result.events)

    return ProcessResult.ok(state, events)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stack_utils.py::TestApplyStackMove -v`
Run: `uv run pytest tests/test_stack_utils.py::TestApplySplitMove -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/game/engine/movement.py tests/test_stack_utils.py
git commit -m "refactor: rewrite movement.py for Stack-only model with apply_split_move"
```

---

### Task 8: Update events.py and rolling.py — AwaitingChoice type change

**Files:**
- Modify: `app/services/game/engine/events.py:142-148` (AwaitingChoice)
- Modify: `app/services/game/engine/events.py:88-89` (StackCaptured description)
- Modify: `app/services/game/engine/rolling.py:186-191` (construct grouped AwaitingChoice)

**Step 1: Update events.py**

In `app/services/game/engine/events.py`:

1. Add import for `LegalMoveGroup`:
```python
from app.schemas.game_engine import LegalMoveGroup, Stack, StackState
```

2. Change `AwaitingChoice.legal_moves` type (line 147):
```python
class AwaitingChoice(GameEvent):
    """Game is waiting for player to choose a move."""

    event_type: Literal["awaiting_choice"] = "awaiting_choice"
    player_id: UUID
    legal_moves: list[LegalMoveGroup] = Field(..., description="Legal moves grouped by parent stack")
    roll_to_allocate: int
```

3. Fix `StackCaptured.capturing_stack_id` description (line 88-89):
```python
    capturing_stack_id: str = Field(
        ..., description="ID of the capturing stack"
    )
```

**Step 2: Update rolling.py to produce grouped AwaitingChoice**

In `app/services/game/engine/rolling.py`:

1. Add import:
```python
from .legal_moves import get_legal_moves, get_legal_move_groups
```

2. Replace lines 183-205 (the legal moves + AwaitingChoice section):
```python
    legal_moves = get_legal_moves(current_player, new_rolls[0], state.board_setup)

    if legal_moves:
        # Build grouped format for frontend
        legal_move_groups = get_legal_move_groups(current_player, new_rolls[0], state.board_setup)
        updated_turn = updated_turn.model_copy(update={"legal_moves": legal_moves})
        events.append(
            AwaitingChoice(
                player_id=player_id,
                legal_moves=legal_move_groups,
                roll_to_allocate=new_rolls[0],
            )
        )
        ...
```

**Step 3: Update movement.py process_after_move AwaitingChoice construction**

In `app/services/game/engine/movement.py`, in `process_after_move`, update the AwaitingChoice construction:

```python
from .legal_moves import get_legal_moves, get_legal_move_groups
```

Replace the AwaitingChoice construction in process_after_move:
```python
        if legal_moves:
            legal_move_groups = get_legal_move_groups(updated_player, remaining_rolls[0], state.board_setup)
            updated_turn = current_turn.model_copy(
                update={
                    "rolls_to_allocate": remaining_rolls,
                    "legal_moves": legal_moves,
                }
            )
            events.append(
                AwaitingChoice(
                    player_id=original_turn.player_id,
                    legal_moves=legal_move_groups,
                    roll_to_allocate=remaining_rolls[0],
                )
            )
```

**Step 4: Run stack_utils tests to verify nothing broke**

Run: `uv run pytest tests/test_stack_utils.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/game/engine/events.py app/services/game/engine/rolling.py app/services/game/engine/movement.py
git commit -m "refactor: AwaitingChoice uses LegalMoveGroup list for frontend"
```

---

### Task 9: Update process.py

**Files:**
- Modify: `app/services/game/engine/process.py:102` (action.stack_id)
- Modify: `app/services/game/engine/process.py:212-236` (check_win_condition)

**Step 1: Write failing test**

Add to `tests/test_stack_utils.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stack_utils.py::TestCheckWinCondition -v`
Expected: FAIL (imports TokenState which no longer exists)

**Step 3: Update process.py**

1. Line 102 — change `action.token_or_stack_id` to `action.stack_id`:
```python
    elif isinstance(action, MoveAction):
        result = process_move(state, action.stack_id, player_id)
```

2. Rewrite `check_win_condition` (lines 212-236):
```python
def check_win_condition(state: GameState) -> UUID | None:
    """Check if any player has won the game.

    A player wins when all their stacks are in HEAVEN.
    """
    from app.schemas.game_engine import StackState

    for player in state.players:
        if all(stack.state == StackState.HEAVEN for stack in player.stacks):
            logger.info("Winner detected: player=%s", player.player_id)
            return player.player_id
    return None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stack_utils.py::TestCheckWinCondition -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/game/engine/process.py tests/test_stack_utils.py
git commit -m "refactor: process.py uses Stack model, action.stack_id"
```

---

### Task 10: Update __init__.py exports

**Files:**
- Modify: `app/services/game/engine/__init__.py`

**Step 1: Update exports**

Add `LegalMoveGroup` to imports and `__all__`, add `get_legal_move_groups`:

```python
from .legal_moves import get_legal_moves, get_legal_move_groups, has_any_legal_moves
```

Add to `__all__`:
```python
    "get_legal_move_groups",
```

**Step 2: Run existing tests to verify no import errors**

Run: `uv run pytest tests/test_stack_utils.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add app/services/game/engine/__init__.py
git commit -m "refactor: update engine __init__ exports"
```

---

### Task 11: Rewrite conftest.py

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Rewrite conftest.py with Stack-based helpers**

```python
# tests/conftest.py
"""Shared fixtures for game engine tests."""

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

# Fixed UUIDs for deterministic testing
PLAYER_1_ID = UUID("00000000-0000-0000-0000-000000000001")
PLAYER_2_ID = UUID("00000000-0000-0000-0000-000000000002")
PLAYER_3_ID = UUID("00000000-0000-0000-0000-000000000003")
PLAYER_4_ID = UUID("00000000-0000-0000-0000-000000000004")


@pytest.fixture
def standard_board_setup() -> BoardSetup:
    """Standard 4-player board setup."""
    return BoardSetup(
        squares_to_win=57,
        squares_to_homestretch=52,
        starting_positions=[0, 13, 26, 39],
        safe_spaces=[0, 13, 26, 39, 8, 21, 34, 47],
        get_out_rolls=[6],
    )


@pytest.fixture
def two_player_board_setup() -> BoardSetup:
    """Two-player board setup."""
    return BoardSetup(
        squares_to_win=57,
        squares_to_homestretch=52,
        starting_positions=[0, 26],
        safe_spaces=[0, 26],
        get_out_rolls=[6],
    )


def create_stack(
    stack_id: str, state: StackState, height: int = 1, progress: int = 0
) -> Stack:
    """Helper to create a stack."""
    return Stack(stack_id=stack_id, state=state, height=height, progress=progress)


def create_stacks_in_hell(count: int = 4) -> list[Stack]:
    """Create stacks all in HELL state (stack_1 through stack_N)."""
    return [create_stack(f"stack_{i}", StackState.HELL, 1, 0) for i in range(1, count + 1)]


def create_player(
    player_id: UUID,
    name: str,
    color: str,
    turn_order: int,
    abs_starting_index: int,
    stacks: list[Stack] | None = None,
) -> Player:
    """Helper to create a player."""
    if stacks is None:
        stacks = create_stacks_in_hell()
    return Player(
        player_id=player_id,
        name=name,
        color=color,
        turn_order=turn_order,
        abs_starting_index=abs_starting_index,
        stacks=stacks,
    )


@pytest.fixture
def player1(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)


@pytest.fixture
def player2(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_2_ID, "Player 2", "blue", 2, 13)


@pytest.fixture
def player3(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_3_ID, "Player 3", "green", 3, 26)


@pytest.fixture
def player4(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_4_ID, "Player 4", "yellow", 4, 39)


@pytest.fixture
def two_player_game_not_started(
    player1: Player, player2: Player, two_player_board_setup: BoardSetup
) -> GameState:
    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=[player1, player2],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=None,
    )


@pytest.fixture
def four_player_game_not_started(
    player1: Player, player2: Player, player3: Player, player4: Player,
    standard_board_setup: BoardSetup,
) -> GameState:
    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=[player1, player2, player3, player4],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=standard_board_setup,
        current_turn=None,
    )


@pytest.fixture
def game_player1_turn(
    player1: Player, player2: Player, two_player_board_setup: BoardSetup
) -> GameState:
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
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=turn,
    )


@pytest.fixture
def game_with_stack_on_road(player2: Player, two_player_board_setup: BoardSetup) -> GameState:
    """Game where player 1 has a stack on the road at progress 10."""
    player1 = create_player(
        player_id=PLAYER_1_ID, name="Player 1", color="red",
        turn_order=1, abs_starting_index=0,
        stacks=[
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ],
    )
    turn = Turn(
        player_id=PLAYER_1_ID, initial_roll=True,
        rolls_to_allocate=[], legal_moves=[],
        current_turn_order=1, extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=turn,
    )
```

**Step 2: Run conftest import check**

Run: `uv run python -c "from tests.conftest import create_stack, create_player, PLAYER_1_ID"`
Expected: No error

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "refactor: rewrite conftest.py with Stack-based helpers"
```

---

### Task 12: Rewrite all test files

Each test file needs updating from Token-based to Stack-based assertions. The event types have changed (TokenMoved -> StackMoved, etc.) and the data model is different (player.stacks instead of player.tokens).

**Files:**
- Rewrite: `tests/test_movement.py`
- Rewrite: `tests/test_get_out_of_hell.py`
- Rewrite: `tests/test_game_finished.py`
- Rewrite: `tests/test_captures.py`
- Rewrite: `tests/test_stacking.py`

**Step 1: Rewrite test_movement.py**

Key changes:
- `create_token(id, TokenState.ROAD, 10)` -> `create_stack("stack_1", StackState.ROAD, 1, 10)`
- `tokens=player1_tokens` -> `stacks=[...]`
- `MoveAction(token_or_stack_id=token_id)` -> `MoveAction(stack_id="stack_1")`
- `TokenMoved` assertions -> `StackMoved` assertions
- `player.tokens` -> `player.stacks`
- Look for stacks by `stack_id` instead of `token_id`

Check `docs/plans/2026-02-27-partial-stack-design.md` for exact event formats.

**Step 2: Rewrite test_get_out_of_hell.py**

Key changes:
- `TokenExitedHell` -> `StackExitedHell`
- `token_exited_hell` event type -> `stack_exited_hell`
- `moved_token.state == TokenState.ROAD` -> `moved.state == StackState.ROAD`
- All `token_id` references -> `stack_id` (e.g., `"stack_1"`)

**Step 3: Rewrite test_game_finished.py**

Key changes:
- `TokenReachedHeaven` -> `StackReachedHeaven`
- `token_reached_heaven` event type -> `stack_reached_heaven`
- `TokenState.HEAVEN` -> `StackState.HEAVEN`
- `player.tokens` -> `player.stacks`

**Step 4: Rewrite test_captures.py**

Key changes:
- `TokenCaptured` -> `StackCaptured`
- `token_captured` event type -> `stack_captured`
- `capturing_token_id` -> `capturing_stack_id`
- Stack objects use `Stack(stack_id=..., state=..., height=..., progress=...)` — no more `tokens=` list inside Stack
- Remove all `player.tokens` references

**Step 5: Rewrite test_stacking.py**

Key changes:
- `StackFormed` and `StackDissolved` are replaced by `StackUpdate`
- `stack_formed` / `stack_dissolved` event types -> `stack_update`
- Stack objects use deterministic IDs: `stack_1_2` for merged stack of pieces 1+2
- `player.stacks` instead of `player.tokens`
- Partial moves use sub-stack IDs (e.g., `"stack_2_3"`) instead of `"stack_id:2"`

**Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add tests/
git commit -m "refactor: rewrite all tests for Stack-only model"
```

---

### Task 13: Final verification and cleanup

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 2: Check for remaining Token/TokenState references**

Run: `grep -r "Token" app/ tests/ --include="*.py" | grep -v "token_or_stack_id" | grep -v "__pycache__"`
Expected: No references to `Token`, `TokenState`, `TokenMoved`, `TokenExitedHell`, `TokenReachedHeaven`, `TokenCaptured`

**Step 3: Check for remaining :count format references**

Run: `grep -r ":count\|:partial_count\|stack_id:\"" app/ tests/ --include="*.py"`
Expected: No matches

**Step 4: Check for next_stack_index references**

Run: `grep -r "next_stack_index" app/ tests/ --include="*.py"`
Expected: No matches

**Step 5: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final cleanup of Token model references"
```

---

## Execution Notes

- **Dependencies between tasks:** Tasks must be done in order (1-13). Each task builds on the previous.
- **Test file for Tasks 1-9:** All new tests go into `tests/test_stack_utils.py` to avoid breaking existing test files that still import old Token model.
- **Task 12 is the largest:** Rewriting 5 test files. Can be split into sub-tasks if needed.
- **Key risk:** The `events.py` + `rolling.py` + `movement.py` changes in Task 8 must be atomic — changing `AwaitingChoice.legal_moves` type without updating all producers will cause runtime errors.
