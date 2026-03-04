# Roll Allocation Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let players see and choose from ALL accumulated rolls (combined view), replacing the current first-usable-roll auto-pick.

**Architecture:** Add `RollMoveGroup` schema, update `AwaitingChoice` to present all rolls with their legal moves, add `roll_value` to `MoveAction` so the player specifies which roll to consume, update engine code to compute combined views and recompute after each move.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest

**Design doc:** `docs/plans/2026-02-28-roll-allocation-redesign.md`

**Tests already written:** `tests/test_multi_roll_allocation.py` and `tests/test_full_turn_flow.py` encode the intended behavior and use the new API. They will fail until implementation is complete. All other test files (11 files) still use the old `MoveAction(stack_id=...)` without `roll_value` and reference `AwaitingChoice.roll_to_allocate` — these need mechanical updates.

---

### Task 1: Add `RollMoveGroup` schema

**Files:**
- Modify: `app/schemas/game_engine.py:60-62` (after `LegalMoveGroup`)

**Step 1: Add the model**

Add `RollMoveGroup` right after `LegalMoveGroup` (line 62):

```python
class RollMoveGroup(BaseModel):
    """Legal moves available for a specific roll value."""
    roll: int
    move_groups: list[LegalMoveGroup]
```

**Step 2: Verify import works**

Run: `uv run python -c "from app.schemas.game_engine import RollMoveGroup; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add app/schemas/game_engine.py
git commit -m "schema: add RollMoveGroup model for multi-roll allocation"
```

---

### Task 2: Add `roll_value` to `MoveAction`

**Files:**
- Modify: `app/services/game/engine/actions.py:15-21`

**Step 1: Add `roll_value` field (optional initially)**

Make `roll_value` optional with `None` default so existing tests don't break immediately:

```python
class MoveAction(BaseModel):
    """Player selects a stack to move."""

    action_type: Literal["move"] = "move"
    stack_id: str = Field(
        ..., description="ID of the stack to move"
    )
    roll_value: int | None = Field(
        None, description="Which roll to consume (required for multi-roll)"
    )
```

**Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/ --ignore=tests/test_multi_roll_allocation.py -x -q`
Expected: All pass (roll_value defaults to None)

**Step 3: Commit**

```bash
git add app/services/game/engine/actions.py
git commit -m "schema: add optional roll_value to MoveAction"
```

---

### Task 3: Update `AwaitingChoice` event

**Files:**
- Modify: `app/services/game/engine/events.py:142-148`

**Step 1: Update the event class**

Replace `legal_moves` and `roll_to_allocate` with `available_moves`:

```python
class AwaitingChoice(GameEvent):
    """Game is waiting for player to choose a move."""

    event_type: Literal["awaiting_choice"] = "awaiting_choice"
    player_id: UUID
    available_moves: list["RollMoveGroup"] = Field(
        ..., description="Legal moves grouped by roll value, then by parent stack"
    )
```

Add the import at the top of events.py:

```python
from app.schemas.game_engine import LegalMoveGroup, RollMoveGroup, Stack, StackState
```

**Step 2: Run the intent tests (expect failures from engine code, not schema)**

Run: `uv run pytest tests/test_full_turn_flow.py::TestBasicTurnFlow -x -q`
Expected: Pass (this test doesn't use AwaitingChoice)

**Step 3: Commit**

```bash
git add app/services/game/engine/events.py
git commit -m "schema: update AwaitingChoice to use available_moves"
```

---

### Task 4: Add `get_all_roll_move_groups()` to legal_moves.py

**Files:**
- Modify: `app/services/game/engine/legal_moves.py` (add after `get_legal_move_groups`, line 87)

**Step 1: Add the helper function**

```python
def get_all_roll_move_groups(
    player: Player, rolls: list[int], board_setup: BoardSetup
) -> list[RollMoveGroup]:
    """Compute legal move groups for all rolls, excluding rolls with no moves.

    Deduplicates roll values (e.g. [6, 6, 3] produces entries for 6 and 3, not two 6s).
    Returns only rolls that have at least one legal move.
    """
    from app.schemas.game_engine import RollMoveGroup

    seen_rolls: set[int] = set()
    result: list[RollMoveGroup] = []

    for roll in rolls:
        if roll in seen_rolls:
            continue
        seen_rolls.add(roll)

        move_groups = get_legal_move_groups(player, roll, board_setup)
        if move_groups:
            result.append(RollMoveGroup(roll=roll, move_groups=move_groups))

    return result
```

Also add the union helper for `Turn.legal_moves` (flat list of all legal stack IDs across all rolls):

```python
def get_all_legal_moves_flat(
    player: Player, rolls: list[int], board_setup: BoardSetup
) -> list[str]:
    """Get the union of all legal move IDs across all rolls (flat list)."""
    seen: set[str] = set()
    result: list[str] = []
    for roll in rolls:
        for move_id in get_legal_moves(player, roll, board_setup):
            if move_id not in seen:
                seen.add(move_id)
                result.append(move_id)
    return result
```

**Step 2: Verify it works**

Run: `uv run python -c "from app.services.game.engine.legal_moves import get_all_roll_move_groups; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add app/services/game/engine/legal_moves.py
git commit -m "feat: add get_all_roll_move_groups helper for combined view"
```

---

### Task 5: Update `rolling.py` to emit combined view

**Files:**
- Modify: `app/services/game/engine/rolling.py:172-220` (the post-roll legal move check)

**Step 1: Replace the first-usable-roll scan with combined view**

Replace the section from line 172 (`# Check for legal moves across all accumulated rolls`) through line 220 (`return ProcessResult.ok(new_state, events)`) with:

```python
    # Check for legal moves across all accumulated rolls (combined view)
    current_player = next(
        p for p in state.players if p.player_id == current_turn.player_id
    )

    from .legal_moves import get_all_roll_move_groups, get_all_legal_moves_flat

    roll_move_groups = get_all_roll_move_groups(current_player, new_rolls, state.board_setup)

    if roll_move_groups:
        legal_moves = get_all_legal_moves_flat(current_player, new_rolls, state.board_setup)
        updated_turn = updated_turn.model_copy(
            update={"rolls_to_allocate": new_rolls, "legal_moves": legal_moves}
        )
        events.append(
            AwaitingChoice(
                player_id=player_id,
                available_moves=roll_move_groups,
            )
        )
        new_state = state.model_copy(
            update={
                "current_event": CurrentEvent.PLAYER_CHOICE,
                "current_turn": updated_turn,
            }
        )
        logger.info(
            "Awaiting player choice: player=%s, rolls_with_moves=%d, total_legal_moves=%d",
            str(player_id)[:8],
            len(roll_move_groups),
            len(legal_moves),
        )
        return ProcessResult.ok(new_state, events)
```

Also remove the now-unused import of `get_legal_moves` at the top (line 24) and replace with:

```python
from .legal_moves import get_all_roll_move_groups, get_all_legal_moves_flat
```

Keep `get_legal_move_groups` import if used elsewhere in the file — check first. (It's used in the existing code but will be removed by this change, so remove it.)

**Step 2: Verify rolling tests pass**

Run: `uv run pytest tests/test_rolling.py -x -q`
Expected: All pass (rolling tests don't inspect AwaitingChoice internals)

**Step 3: Commit**

```bash
git add app/services/game/engine/rolling.py
git commit -m "feat: rolling.py emits combined roll view in AwaitingChoice"
```

---

### Task 6: Update `process_move()` to use `roll_value`

**Files:**
- Modify: `app/services/game/engine/movement.py:44-136`
- Modify: `app/services/game/engine/process.py:101-102`

**Step 1: Update `process.py` dispatch to pass `roll_value`**

Change line 101-102 in `process.py`:

```python
    elif isinstance(action, MoveAction):
        result = process_move(state, action.stack_id, action.roll_value, player_id)
```

**Step 2: Update `process_move()` signature and roll selection**

Update the function signature and roll selection logic in `movement.py`:

```python
def process_move(state: GameState, stack_id: str, roll_value: int | None, player_id: UUID) -> ProcessResult:
```

Replace the roll selection block (lines 63-68):

```python
    if not current_turn.rolls_to_allocate:
        logger.error("process_move called with no rolls to allocate")
        return ProcessResult.failure("NO_ROLLS", "No rolls to allocate")

    # Determine which roll to use
    if roll_value is not None:
        if roll_value not in current_turn.rolls_to_allocate:
            return ProcessResult.failure(
                "INVALID_ROLL",
                f"Roll {roll_value} is not in rolls_to_allocate",
            )
        roll = roll_value
    else:
        # Legacy fallback: use first roll (for tests not yet updated)
        roll = current_turn.rolls_to_allocate[0]
```

**Step 3: Update roll consumption in the CAPTURE_CHOICE branch (lines 128-133)**

Replace:
```python
        updated_turn = result.state.current_turn.model_copy(
            update={"rolls_to_allocate": current_turn.rolls_to_allocate[1:]}
        )
```

With:
```python
        remaining = list(current_turn.rolls_to_allocate)
        remaining.remove(roll)
        updated_turn = result.state.current_turn.model_copy(
            update={"rolls_to_allocate": remaining}
        )
```

**Step 4: Verify basic movement tests still work**

Run: `uv run pytest tests/test_movement.py -x -q`
Expected: All pass (they use MoveAction without roll_value, falling back to first roll)

**Step 5: Commit**

```bash
git add app/services/game/engine/movement.py app/services/game/engine/process.py
git commit -m "feat: process_move accepts roll_value parameter"
```

---

### Task 7: Update `process_after_move()` to use combined view

**Files:**
- Modify: `app/services/game/engine/movement.py:446-583` (`process_after_move`)

**Step 1: Replace roll consumption and legal move scan with combined view**

Replace the roll consumption and remaining-rolls logic. The function currently does `remaining_rolls = original_turn.rolls_to_allocate[1:]`. Change to consume by value:

```python
def process_after_move(
    state: GameState,
    events: list[AnyGameEvent],
    original_turn: Turn,
    used_roll: int,
) -> ProcessResult:
    current_turn = state.current_turn
    if current_turn is None:
        logger.error("Turn lost during move processing")
        return ProcessResult.failure("NO_ACTIVE_TURN", "Turn lost during move")

    # Remove the used roll by value (not by index)
    remaining_rolls = list(original_turn.rolls_to_allocate)
    remaining_rolls.remove(used_roll)
    logger.debug(
        "Post-move: used_roll=%d, remaining_rolls=%s, extra_rolls=%d",
        used_roll,
        remaining_rolls,
        current_turn.extra_rolls,
    )

    # Get updated player
    updated_player = next(p for p in state.players if p.player_id == original_turn.player_id)

    # Check for remaining rolls with legal moves (combined view)
    if remaining_rolls:
        from .legal_moves import get_all_roll_move_groups, get_all_legal_moves_flat

        roll_move_groups = get_all_roll_move_groups(updated_player, remaining_rolls, state.board_setup)

        if roll_move_groups:
            legal_moves = get_all_legal_moves_flat(updated_player, remaining_rolls, state.board_setup)
            updated_turn = current_turn.model_copy(
                update={
                    "rolls_to_allocate": remaining_rolls,
                    "legal_moves": legal_moves,
                }
            )
            events.append(
                AwaitingChoice(
                    player_id=original_turn.player_id,
                    available_moves=roll_move_groups,
                )
            )
            new_state = state.model_copy(
                update={
                    "current_event": CurrentEvent.PLAYER_CHOICE,
                    "current_turn": updated_turn,
                }
            )
            logger.info(
                "More moves available: player=%s, rolls_with_moves=%d",
                str(original_turn.player_id)[:8],
                len(roll_move_groups),
            )
            return ProcessResult.ok(new_state, events)

        # No legal moves for any remaining roll — discard all
        logger.debug(
            "No legal moves for any remaining rolls %s, clearing",
            remaining_rolls,
        )
        remaining_rolls = []

    # Check for extra rolls from captures
    if current_turn.extra_rolls > 0:
        logger.info(
            "Granting capture bonus roll: player=%s, extra_rolls_remaining=%d",
            str(original_turn.player_id)[:8],
            current_turn.extra_rolls,
        )
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

    # End turn - move to next player
    logger.info(
        "Turn ending: player=%s, reason=all_rolls_used",
        str(original_turn.player_id)[:8],
    )
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
```

**Step 2: Run movement tests**

Run: `uv run pytest tests/test_movement.py -x -q`
Expected: All pass

**Step 3: Commit**

```bash
git add app/services/game/engine/movement.py
git commit -m "feat: process_after_move uses combined roll view"
```

---

### Task 8: Update `resume_after_capture()` to use combined view

**Files:**
- Modify: `app/services/game/engine/movement.py:586-678` (`resume_after_capture`)

**Step 1: Replace the scan with combined view**

Same pattern as Task 7 but without consuming a roll (the roll was already consumed). Replace the remaining-rolls scan (lines 603-637) with:

```python
    remaining_rolls = current_turn.rolls_to_allocate
    updated_player = next(p for p in state.players if p.player_id == current_turn.player_id)

    # Check for remaining rolls with legal moves (combined view)
    if remaining_rolls:
        from .legal_moves import get_all_roll_move_groups, get_all_legal_moves_flat

        roll_move_groups = get_all_roll_move_groups(updated_player, remaining_rolls, state.board_setup)

        if roll_move_groups:
            legal_moves = get_all_legal_moves_flat(updated_player, remaining_rolls, state.board_setup)
            updated_turn = current_turn.model_copy(
                update={
                    "rolls_to_allocate": remaining_rolls,
                    "legal_moves": legal_moves,
                }
            )
            events.append(
                AwaitingChoice(
                    player_id=current_turn.player_id,
                    available_moves=roll_move_groups,
                )
            )
            new_state = state.model_copy(
                update={
                    "current_event": CurrentEvent.PLAYER_CHOICE,
                    "current_turn": updated_turn,
                }
            )
            return ProcessResult.ok(new_state, events)
```

Keep the extra_rolls and end-turn blocks identical to existing code.

**Step 2: Run capture choice tests**

Run: `uv run pytest tests/test_capture_choice.py -x -q`
Expected: All pass

**Step 3: Commit**

```bash
git add app/services/game/engine/movement.py
git commit -m "feat: resume_after_capture uses combined roll view"
```

---

### Task 9: Update validation to check `roll_value`

**Files:**
- Modify: `app/services/game/engine/validation.py:178-200`

**Step 1: Add roll_value validation**

Update the MoveAction validation block:

```python
    elif isinstance(action, MoveAction):
        if state.current_event != CurrentEvent.PLAYER_CHOICE:
            logger.warning(
                "Validation failed: INVALID_ACTION (move), expected=%s, got=%s",
                CurrentEvent.PLAYER_CHOICE.value,
                state.current_event.value,
            )
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot move - waiting for a different action",
            )

        # Check move is in legal moves (flat union across all rolls)
        if action.stack_id not in state.current_turn.legal_moves:
            logger.warning(
                "Validation failed: ILLEGAL_MOVE, requested=%s, legal_moves=%s",
                action.stack_id,
                state.current_turn.legal_moves,
            )
            return ValidationResult.error(
                "ILLEGAL_MOVE",
                f"'{action.stack_id}' is not a legal move",
            )

        # Validate roll_value if provided
        if action.roll_value is not None:
            if action.roll_value not in state.current_turn.rolls_to_allocate:
                logger.warning(
                    "Validation failed: INVALID_ROLL, roll_value=%d, rolls=%s",
                    action.roll_value,
                    state.current_turn.rolls_to_allocate,
                )
                return ValidationResult.error(
                    "INVALID_ROLL",
                    f"Roll {action.roll_value} is not in rolls_to_allocate",
                )

            # Verify the stack is legal for this specific roll
            from app.services.game.engine.legal_moves import get_legal_moves

            current_player = next(
                p for p in state.players if p.player_id == state.current_turn.player_id
            )
            roll_legal_moves = get_legal_moves(
                current_player, action.roll_value, state.board_setup
            )
            if action.stack_id not in roll_legal_moves:
                logger.warning(
                    "Validation failed: ILLEGAL_MOVE_FOR_ROLL, stack=%s, roll=%d, legal=%s",
                    action.stack_id,
                    action.roll_value,
                    roll_legal_moves,
                )
                return ValidationResult.error(
                    "ILLEGAL_MOVE",
                    f"'{action.stack_id}' is not a legal move for roll {action.roll_value}",
                )
```

**Step 2: Run validation tests**

Run: `uv run pytest tests/test_validation.py -x -q`
Expected: All pass

**Step 3: Commit**

```bash
git add app/services/game/engine/validation.py
git commit -m "feat: validate roll_value in MoveAction"
```

---

### Task 10: Mechanical update — add `roll_value` to all remaining test files

**Files to update (11 files):**
- `tests/test_movement.py` — MoveAction calls use the roll from `rolls_to_allocate[0]`
- `tests/test_captures.py` — same pattern
- `tests/test_stacking.py` — same pattern
- `tests/test_stack_utils.py` — same pattern
- `tests/test_get_out_of_hell.py` — same pattern
- `tests/test_hell_exit_collisions.py` — same pattern
- `tests/test_homestretch_heaven.py` — same pattern
- `tests/test_game_finished.py` — same pattern
- `tests/test_capture_chains.py` — same pattern
- `tests/test_capture_choice.py` — same pattern
- `tests/test_validation.py` — same pattern

**Pattern:** Each test constructs state with `rolls_to_allocate=[X]` and calls `MoveAction(stack_id="Y")`. Change to `MoveAction(stack_id="Y", roll_value=X)`.

**For tests that go through `RollAction` first:** Trace the accumulated rolls and use the correct one.

**Step 1: Update each file**

For each file, find all `MoveAction(stack_id="...")` calls and add the `roll_value` from the test's setup. The roll is always deterministic from the test context — it's whatever `rolls_to_allocate` was set to, or whatever was accumulated via `RollAction` calls.

**Step 2: Also update `AwaitingChoice` assertions**

In files that assert on `awaiting.roll_to_allocate` or `awaiting.legal_moves`, update to use `awaiting.available_moves` with the helper pattern:

```python
# Old:
assert awaiting.roll_to_allocate == 6
offered = {m for g in awaiting.legal_moves for m in g.moves}

# New:
rolls_offered = [rmg.roll for rmg in awaiting.available_moves]
assert 6 in rolls_offered
offered = {m for rmg in awaiting.available_moves for g in rmg.move_groups for m in g.moves}
```

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: Many tests still fail (engine code uses new AwaitingChoice but old tests may not match)

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: add roll_value to MoveAction across all test files"
```

---

### Task 11: Make `roll_value` required on `MoveAction`

**Files:**
- Modify: `app/services/game/engine/actions.py:15-22`

**Step 1: Remove the `None` default**

```python
class MoveAction(BaseModel):
    """Player selects a stack to move."""

    action_type: Literal["move"] = "move"
    stack_id: str = Field(
        ..., description="ID of the stack to move"
    )
    roll_value: int = Field(
        ..., description="Which roll value to consume from rolls_to_allocate"
    )
```

**Step 2: Remove the legacy fallback in `process_move`**

In `movement.py`, simplify the roll selection:

```python
    if roll_value not in current_turn.rolls_to_allocate:
        return ProcessResult.failure(
            "INVALID_ROLL",
            f"Roll {roll_value} is not in rolls_to_allocate",
        )
    roll = roll_value
```

Update signature to `roll_value: int` (not `int | None`).

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add app/services/game/engine/actions.py app/services/game/engine/movement.py
git commit -m "feat: make roll_value required on MoveAction"
```

---

### Task 12: Clean up unused imports and verify

**Files:**
- Review: `app/services/game/engine/rolling.py` — remove unused `get_legal_moves`, `get_legal_move_groups` imports
- Review: `app/services/game/engine/movement.py` — remove unused `get_legal_moves`, `get_legal_move_groups` imports, remove unused `AwaitingChoice` fields references
- Review: `app/services/game/engine/events.py` — ensure `LegalMoveGroup` import kept (used by `RollMoveGroup`)

**Step 1: Run linter**

Run: `uv run ruff check app/services/game/engine/`
Fix any import or style issues.

**Step 2: Run formatter**

Run: `uv run ruff format app/services/game/engine/ tests/`

**Step 3: Run full test suite one final time**

Run: `uv run pytest tests/ -v`
Expected: All pass, no warnings

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: clean up imports and formatting after roll allocation redesign"
```

---

### Task 13: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update the Known Implementation Gaps section**

Remove: "Roll allocation is FIFO (`rolls[0]`) — should allow player choice of which roll to use"
Remove: "No-legal-moves for a roll ends turn — should skip to next accumulated roll"

Add to Patterns Used: "Multi-roll allocation: `AwaitingChoice` presents all accumulated rolls with legal moves via `RollMoveGroup`; player specifies `roll_value` in `MoveAction`"

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for roll allocation redesign"
```
