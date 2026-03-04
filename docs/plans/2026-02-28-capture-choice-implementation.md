# Capture Choice Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the capture choice mechanic so players choose which opponent to capture when multiple capturable targets occupy the same square.

**Architecture:** Add `PendingCapture` to `Turn` schema, refactor `handle_road_collision` to partition stacking from opponent collisions and branch on capturable count, rewrite the `process_capture_choice` stub to validate/execute/resume flow, and fix the `process.py` dispatch.

**Tech Stack:** Python 3.12, Pydantic models, pytest

**Design doc:** `docs/plans/2026-02-28-capture-choice-design.md`

---

### Task 1: Add PendingCapture schema to Turn

**Files:**
- Modify: `app/schemas/game_engine.py`

**Step 1: Add PendingCapture model and field**

Add `PendingCapture` before the `Turn` class, and add the field to `Turn`:

```python
class PendingCapture(BaseModel):
    """Context stored when a move triggers a multi-target capture choice."""
    moving_stack_id: str
    position: int
    capturable_targets: list[str]  # "{player_id}:{stack_id}" format


class Turn(BaseModel):
    player_id: UUID
    initial_roll: bool = True
    rolls_to_allocate: list[int] = Field(default_factory=list)
    legal_moves: list[str] = Field(default_factory=list)
    current_turn_order: int
    extra_rolls: int = 0
    pending_capture: PendingCapture | None = None
```

**Step 2: Run tests to verify no regressions**

Run: `uv run pytest -x -q`
Expected: Same 5 failures as before (capture_choice tests), no new failures.

**Step 3: Commit**

```
git add app/schemas/game_engine.py
git commit -m "schema: add PendingCapture model to Turn"
```

---

### Task 2: Refactor handle_road_collision

**Files:**
- Modify: `app/services/game/engine/movement.py:576-622`
- Read: `app/services/game/engine/captures.py` (for `get_absolute_position`, `resolve_stacking`, `resolve_capture`)

**Context:** Currently `handle_road_collision` iterates all collisions and calls `resolve_collision` for each. This auto-captures every opponent. We need to:
1. Partition into same-player (stacking) and different-player (opponent) collisions
2. Auto-resolve all stacking
3. Filter opponents by height (capturable = moving height >= opponent height)
4. Branch: 0 capturable → done, 1 capturable → auto-capture, 2+ → emit `AwaitingCaptureChoice`

**Step 1: Rewrite handle_road_collision**

Replace the function body at `movement.py:576-622` with:

```python
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

    # Partition: same-player (stacking) vs opponent collisions
    stacking_collisions = []
    opponent_collisions = []
    for other_player, other_piece in collisions:
        if other_player.player_id == player.player_id:
            stacking_collisions.append((other_player, other_piece))
        else:
            opponent_collisions.append((other_player, other_piece))

    # 1. Auto-resolve all stacking (same-player merges)
    for other_player, other_piece in stacking_collisions:
        collision_result = resolve_collision(
            state, player, moved_piece, other_player, other_piece, events
        )
        if collision_result.state is not None:
            state = collision_result.state
            # Update moved_piece and player references after merge
            player = next(p for p in state.players if p.player_id == player.player_id)
            # Find the merged stack (moved_piece may have been replaced)
            merged = next(
                (s for s in player.stacks if s.progress == moved_piece.progress and s.state == StackState.ROAD),
                moved_piece,
            )
            moved_piece = merged
        events.extend(collision_result.events)

    if not opponent_collisions:
        return ProcessResult.ok(state, events)

    # 2. Check safe space — no captures on safe spaces
    abs_pos = get_absolute_position(moved_piece, player, board_setup)
    if abs_pos in board_setup.safe_spaces:
        return ProcessResult.ok(state, events)

    # 3. Filter to capturable opponents (moving height >= opponent height)
    capturable = [
        (op, piece) for op, piece in opponent_collisions
        if moved_piece.height >= piece.height
    ]

    if len(capturable) == 0:
        # No capturable opponents (all too tall) — coexist
        return ProcessResult.ok(state, events)

    if len(capturable) == 1:
        # Single capturable opponent — auto-capture
        other_player, other_piece = capturable[0]
        collision_result = resolve_capture(
            state, player, moved_piece, other_player, other_piece, events
        )
        if collision_result.state is not None:
            state = collision_result.state
        events.extend(collision_result.events)
        return ProcessResult.ok(state, events)

    # 4. Multiple capturable opponents — require player choice
    targets = [
        f"{op.player_id}:{piece.stack_id}" for op, piece in capturable
    ]
    pending = PendingCapture(
        moving_stack_id=moved_piece.stack_id,
        position=abs_pos,
        capturable_targets=targets,
    )
    updated_turn = state.current_turn.model_copy(
        update={"pending_capture": pending}
    )
    new_state = state.model_copy(
        update={
            "current_event": CurrentEvent.CAPTURE_CHOICE,
            "current_turn": updated_turn,
        }
    )
    events.append(
        AwaitingCaptureChoice(
            player_id=player.player_id,
            options=targets,
        )
    )
    return ProcessResult.ok(new_state, events)
```

**New imports needed at top of movement.py:**

```python
from app.schemas.game_engine import PendingCapture
from .captures import detect_collisions, resolve_collision, resolve_capture, get_absolute_position
```

Note: `resolve_capture` and `get_absolute_position` are new imports (previously only `detect_collisions` and `resolve_collision` were imported). Also add `AwaitingCaptureChoice` to the events import.

**Step 2: Run the collision-related tests**

Run: `uv run pytest tests/test_capture_choice.py::TestSingleOpponentAutoResolved tests/test_capture_choice.py::TestMultipleOpponentsRequireChoice tests/test_capture_choice.py::TestCaptureChoiceHeightFilter tests/test_capture_choice.py::TestDetectMultipleCollisions tests/test_captures.py -v`

Expected:
- `TestSingleOpponentAutoResolved` — PASS (auto-capture preserved)
- `TestMultipleOpponentsRequireChoice` — PASS (new branching logic)
- `TestCaptureChoiceHeightFilter` — PASS (height filter + auto-capture fallback)
- `TestDetectMultipleCollisions` — PASS (unchanged detection layer)
- `test_captures.py` — all PASS (existing capture behavior preserved)

**Step 3: Run full suite to check for regressions**

Run: `uv run pytest -x -q`
Expected: Only 3 remaining failures (the `process_capture_choice` tests: resolution, validation, extra rolls).

**Step 4: Commit**

```
git add app/services/game/engine/movement.py
git commit -m "feat: refactor handle_road_collision for multi-target capture choice"
```

---

### Task 3: Implement process_capture_choice

**Files:**
- Modify: `app/services/game/engine/captures.py:424-443`
- Read: `app/services/game/engine/movement.py` (for `process_after_move`)

**Context:** The stub currently returns an empty `CollisionResult`. Rewrite to return `ProcessResult`. It needs to: validate choice, execute capture, grant extra rolls, clear pending_capture, and resume post-move flow.

**Step 1: Add imports to captures.py**

Add to the imports section:

```python
from .validation import ProcessResult
from .events import AwaitingCaptureChoice, RollGranted
```

**Step 2: Rewrite process_capture_choice**

Replace the stub at `captures.py:424-443`:

```python
def process_capture_choice(
    state: GameState,
    choice: str,
    player_id: UUID,
) -> ProcessResult:
    """Process a capture choice made by the player.

    Validates the choice against pending_capture targets, executes the
    capture, grants extra rolls, clears pending state, and resumes
    post-move flow (remaining rolls / extra rolls / turn end).
    """
    current_turn = state.current_turn
    if current_turn is None or current_turn.pending_capture is None:
        return ProcessResult.failure(
            "NO_PENDING_CAPTURE", "No pending capture to resolve"
        )

    pending = current_turn.pending_capture

    # Validate choice is among capturable targets
    if choice not in pending.capturable_targets:
        return ProcessResult.failure(
            "INVALID_CAPTURE_TARGET",
            f"'{choice}' is not a valid capture target. "
            f"Valid targets: {pending.capturable_targets}",
        )

    # Parse "{player_id}:{stack_id}"
    parts = choice.split(":", 1)
    if len(parts) != 2:
        return ProcessResult.failure(
            "INVALID_CHOICE_FORMAT",
            f"Choice must be in 'player_id:stack_id' format, got: {choice}",
        )
    target_player_id_str, target_stack_id = parts

    try:
        target_player_id = UUID(target_player_id_str)
    except ValueError:
        return ProcessResult.failure(
            "INVALID_CHOICE_FORMAT",
            f"Invalid player ID in choice: {target_player_id_str}",
        )

    # Find the target player and stack
    target_player = next(
        (p for p in state.players if p.player_id == target_player_id), None
    )
    if target_player is None:
        return ProcessResult.failure(
            "PLAYER_NOT_FOUND", f"Player {target_player_id} not found"
        )

    target_stack = next(
        (s for s in target_player.stacks if s.stack_id == target_stack_id), None
    )
    if target_stack is None:
        return ProcessResult.failure(
            "STACK_NOT_FOUND", f"Stack {target_stack_id} not found"
        )

    # Find the capturing player and their moving stack
    capturing_player = next(
        p for p in state.players if p.player_id == player_id
    )
    moving_stack = next(
        (s for s in capturing_player.stacks if s.stack_id == pending.moving_stack_id),
        None,
    )
    if moving_stack is None:
        return ProcessResult.failure(
            "MOVING_STACK_NOT_FOUND",
            f"Moving stack {pending.moving_stack_id} not found",
        )

    # Execute capture
    events: list[AnyGameEvent] = []
    collision_result = resolve_capture(
        state, capturing_player, moving_stack, target_player, target_stack, events
    )
    if collision_result.state is not None:
        state = collision_result.state
    events.extend(collision_result.events)

    # Clear pending_capture
    updated_turn = state.current_turn.model_copy(
        update={"pending_capture": None}
    )
    state = state.model_copy(update={"current_turn": updated_turn})

    # Resume post-move flow (remaining rolls, extra rolls, or turn end)
    from .movement import process_after_move

    # The roll was already consumed by the move that triggered the collision.
    # We pass used_roll=0 as a sentinel since no roll is being consumed here.
    # process_after_move will check remaining rolls and extra rolls.
    return process_after_move(
        state, events, state.current_turn, used_roll=0
    )
```

**Important:** The `used_roll=0` approach won't work with `process_after_move` because it does `remaining_rolls = original_turn.rolls_to_allocate[1:]` which would incorrectly drop a roll. Instead, we should inline the post-move resume logic. Let me revise:

Replace the last section (after "Clear pending_capture") with:

```python
    # Clear pending_capture
    updated_turn = state.current_turn.model_copy(
        update={"pending_capture": None}
    )
    state = state.model_copy(update={"current_turn": updated_turn})

    # Resume post-move flow
    from .movement import resume_after_capture
    return resume_after_capture(state, events)
```

This requires extracting a small helper from `process_after_move` — see Task 4.

**Step 3: Commit (partial — depends on Task 4)**

Do NOT commit yet. This function calls `resume_after_capture` which doesn't exist yet.

---

### Task 4: Extract resume_after_capture helper from movement.py

**Files:**
- Modify: `app/services/game/engine/movement.py`

**Context:** `process_after_move` does: remove used roll → check remaining rolls → check extra rolls → end turn. After a capture choice, the roll was already consumed. We need the "check remaining rolls → check extra rolls → end turn" part without the "remove used roll" part. Extract this as `resume_after_capture`.

**Step 1: Add resume_after_capture function**

Add after `process_after_move` in `movement.py`:

```python
def resume_after_capture(
    state: GameState,
    events: list[AnyGameEvent],
) -> ProcessResult:
    """Resume post-move flow after a capture choice is resolved.

    Unlike process_after_move, this does NOT consume a roll (the roll
    was already consumed by the move that triggered the collision).
    Checks remaining rolls, extra rolls, or ends turn.
    """
    current_turn = state.current_turn
    if current_turn is None:
        return ProcessResult.failure("NO_ACTIVE_TURN", "Turn lost during capture choice")

    remaining_rolls = current_turn.rolls_to_allocate
    updated_player = next(p for p in state.players if p.player_id == current_turn.player_id)

    # Check for remaining rolls — find first with legal moves
    if remaining_rolls:
        usable_index = None
        legal_moves: list[str] = []
        for i, roll in enumerate(remaining_rolls):
            moves = get_legal_moves(updated_player, roll, state.board_setup)
            if moves:
                usable_index = i
                legal_moves = moves
                break

        if usable_index is not None:
            usable_roll = remaining_rolls[usable_index]
            reordered = [usable_roll] + remaining_rolls[:usable_index] + remaining_rolls[usable_index + 1:]
            legal_move_groups = get_legal_move_groups(updated_player, usable_roll, state.board_setup)
            updated_turn = current_turn.model_copy(
                update={
                    "rolls_to_allocate": reordered,
                    "legal_moves": legal_moves,
                }
            )
            events.append(
                AwaitingChoice(
                    player_id=current_turn.player_id,
                    legal_moves=legal_move_groups,
                    roll_to_allocate=usable_roll,
                )
            )
            new_state = state.model_copy(
                update={
                    "current_event": CurrentEvent.PLAYER_CHOICE,
                    "current_turn": updated_turn,
                }
            )
            return ProcessResult.ok(new_state, events)

    # Check for extra rolls from captures
    if current_turn.extra_rolls > 0:
        events.append(RollGranted(player_id=current_turn.player_id, reason="capture_bonus"))
        updated_turn = current_turn.model_copy(
            update={
                "rolls_to_allocate": [],
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
    next_turn_order = get_next_turn_order(current_turn.current_turn_order, len(state.players))
    next_player = next(p for p in state.players if p.turn_order == next_turn_order)

    events.append(
        TurnEnded(
            player_id=current_turn.player_id,
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
```

**Step 2: Run capture choice tests**

Run: `uv run pytest tests/test_capture_choice.py -v`

Expected: All 10 tests PASS (5 previously passing + 5 previously failing).

**Step 3: Commit Tasks 3+4 together**

```
git add app/services/game/engine/captures.py app/services/game/engine/movement.py
git commit -m "feat: implement process_capture_choice and resume_after_capture"
```

---

### Task 5: Fix process.py dispatch

**Files:**
- Modify: `app/services/game/engine/process.py:104-110`

**Context:** `process_capture_choice` now returns `ProcessResult` directly. The current dispatch wraps it awkwardly with a `CollisionResult` null check. Simplify.

**Step 1: Fix dispatch**

Replace lines 104-110:

```python
    elif isinstance(action, CaptureChoiceAction):
        result = process_capture_choice(state, action.choice, player_id)
```

Remove the `if result.state is None` block — `process_capture_choice` now returns proper `ProcessResult` with `success=False` for failures, which the existing `result.success` check at line 120 handles.

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: 161 tests, 156 passed, 0 failed, 5 capture_choice tests now passing. Only pre-existing xfail remains.

**Step 3: Commit**

```
git add app/services/game/engine/process.py
git commit -m "fix: simplify capture choice dispatch in process.py"
```

---

### Task 6: Final verification and cleanup

**Step 1: Run full test suite**

Run: `uv run pytest -v --tb=short`
Expected: 0 failures (the 5 capture_choice tests now pass).

**Step 2: Run linter**

Run: `uv run ruff check app/services/game/engine/captures.py app/services/game/engine/movement.py app/services/game/engine/process.py app/schemas/game_engine.py`
Expected: No new lint errors from our changes.

**Step 3: Update CLAUDE.md**

Remove `process_capture_choice()` from the "Known Implementation Gaps" section since it's now implemented.

**Step 4: Commit**

```
git add CLAUDE.md
git commit -m "docs: remove capture choice from known implementation gaps"
```
