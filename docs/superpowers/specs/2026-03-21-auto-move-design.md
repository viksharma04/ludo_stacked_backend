# Auto-Move: Skip Player Choice When Only One Legal Move Exists

**Date:** 2026-03-21
**Status:** Draft

## Problem

When a player has only one possible move after rolling, the game still emits `AwaitingChoice` and waits for a `MoveAction` from the client. This adds unnecessary round-trips and delays gameplay for situations where the player has no real decision to make.

## Solution

Extract a shared helper function that replaces the current "compute moves → emit AwaitingChoice" pattern. When exactly one legal move exists, the engine auto-executes it immediately, emitting all normal movement events. When multiple options exist, behavior is unchanged.

## Trigger Condition

Auto-move fires when ALL of the following are true:
- `get_all_roll_move_groups` returns exactly **1** `RollMoveGroup`
- That group contains exactly **1** `LegalMoveGroup`
- That group contains exactly **1** move ID

Any additional options (multiple rolls with moves, multiple stacks, split options) prevent auto-move.

## Design

### Shared Helper

New function in `movement.py`:

```python
def resolve_moves_or_await(
    state: GameState,
    player: Player,
    rolls: list[int],
    events: list[AnyGameEvent],
) -> ProcessResult | None
```

Logic:
1. Compute `roll_move_groups` via `get_all_roll_move_groups(player, rolls, board_setup)`
2. If no legal moves: return `None` (caller handles turn end / extra rolls)
3. If exactly one option (1 RollMoveGroup, 1 LegalMoveGroup, 1 move ID): call `process_move(state, stack_id, roll_value, player_id)` directly, prepend the caller's events, return the result
4. If multiple options: emit `AwaitingChoice`, update turn with legal moves, set state to `PLAYER_CHOICE`, return result

### Call Sites

Three locations replace their current "compute moves → emit AwaitingChoice" blocks with a call to `resolve_moves_or_await`:

1. **`rolling.py:process_roll`** (lines ~171-201) — after a non-6 roll
2. **`movement.py:process_after_move`** (lines ~526-558) — after consuming a roll, checking remaining rolls
3. **`movement.py:resume_after_capture`** (lines ~664-691) — after capture choice resolution

Each caller: if `resolve_moves_or_await` returns a `ProcessResult`, return it. If `None`, fall through to existing "no legal moves" logic (turn end, extra rolls, etc.).

### Recursion

When auto-move fires, `process_move` is called, which internally calls `process_after_move`, which calls `resolve_moves_or_await` again. This creates natural chaining: if the remaining rolls also have exactly one option, they auto-execute too.

The recursion is bounded because:
- Each auto-move consumes one roll from `rolls_to_allocate` (finite list)
- Extra rolls (capture bonus, heaven bonus) transition state to `PLAYER_ROLL`, requiring a `RollAction` from the player
- Turn end terminates the chain
- Maximum recursion depth is bounded by the number of rolls per turn (at most ~6 in extreme cases), well within Python's stack limit

### Auto-Move Failure

An auto-move failure (e.g., `process_move` returning an error) is a logic error — the engine selected a move from its own computed legal moves. If this happens, propagate the failure `ProcessResult` as-is. This surfaces bugs rather than silently masking them.

### Interaction with Capture Choice

If an auto-executed move causes a collision with multiple capturable opponents, `process_move` returns state in `CAPTURE_CHOICE`. The auto-move chain pauses. The player must send a `CaptureChoiceAction`. After resolution, `resume_after_capture` may trigger further auto-moves via the same helper.

### Events

Auto-move emits the same events as a manual move. No new event types. No `AwaitingChoice` is emitted when auto-move fires.

Examples:
- **Road move:** `DiceRolled → StackMoved → TurnEnded → TurnStarted → RollGranted`
- **Hell exit:** `DiceRolled → StackExitedHell → TurnEnded → TurnStarted → RollGranted`
- **Auto-move + capture:** `DiceRolled → StackMoved → StackCaptured → RollGranted`
- **Chained auto-moves:** `DiceRolled → StackMoved → StackMoved → TurnEnded → TurnStarted → RollGranted`

### Out of Scope

- `AwaitingCaptureChoice` — not affected by auto-move
- Rolling — player always sends `RollAction`
- New event types — not needed

## Files Changed

- `app/services/game/engine/movement.py` — add `resolve_moves_or_await`, update `process_after_move` and `resume_after_capture`
- `app/services/game/engine/rolling.py` — update `process_roll` to use `resolve_moves_or_await`
- `tests/test_auto_move.py` — new test file

## Tests

New test file `tests/test_auto_move.py`:

1. **Single move auto-executes** — one stack on ROAD, roll produces one legal move → `StackMoved` emitted, no `AwaitingChoice`
2. **Multiple moves emit AwaitingChoice** — two stacks on ROAD, roll has moves for both → `AwaitingChoice` emitted (regression)
3. **Split option prevents auto-move** — height-2 stack, roll divisible by both 1 and 2 → `AwaitingChoice` emitted
4. **Auto-move chains across remaining rolls** — rolls [3, 5], each with one move → both auto-execute
5. **Auto-move from resume_after_capture** — after capture resolution, remaining rolls have one option → auto-executes
6. **Hell exit auto-move** — only stack in HELL, roll is 6 → `StackExitedHell` emitted, no `AwaitingChoice`
7. **Auto-move triggers capture with bonus roll** — single stack, move lands on single capturable opponent → auto-move fires, capture auto-resolves, extra roll granted, state transitions to `PLAYER_ROLL`
8. **Auto-move reaches heaven with bonus rolls** — only legal move sends stack to HEAVEN → auto-move fires, `StackReachedHeaven` emitted, `heaven_extra_rolls` granted, state transitions to `PLAYER_ROLL`
9. **Height-2 stack with only full-stack move legal** — split would overshoot `squares_to_win`, only full-stack move valid → auto-move fires

## Existing Test Migration

Some existing tests expect `AwaitingChoice` in scenarios where auto-move will now fire instead. These tests will need updating to reflect the new behavior (no `AwaitingChoice`, movement events emitted directly). Affected tests will be identified during implementation and updated to match the new expected event sequence.
