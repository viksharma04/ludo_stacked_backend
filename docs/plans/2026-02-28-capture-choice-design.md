# Capture Choice Design

Date: 2026-02-28

## Problem

When a player's stack lands on a square occupied by multiple opponent stacks, the engine currently captures all of them in a loop. The correct behavior: the player chooses which one to capture. Only stacks the player CAN capture (height >= target height) are offered as options. If only one opponent is capturable, auto-capture (no choice needed).

## Design

### Schema: PendingCapture on Turn

Add a `PendingCapture` model to store context between the move that triggers a multi-target collision and the subsequent `CaptureChoiceAction`:

```python
class PendingCapture(BaseModel):
    moving_stack_id: str          # The player's stack that landed
    position: int                 # Absolute board position of the collision
    capturable_targets: list[str] # Options in "{player_id}:{stack_id}" format

class Turn(BaseModel):
    ...existing fields...
    pending_capture: PendingCapture | None = None
```

Set when entering `CAPTURE_CHOICE`, cleared after resolution.

### handle_road_collision refactor (movement.py)

Current behavior: blind loop over all collisions, calling `resolve_collision` for each.

New behavior:

1. Partition collisions into same-player (stacking) and opponent collisions
2. Process all same-player collisions first — stacking always auto-resolves
3. Filter opponent collisions by height — only keep where `moved_piece.height >= opponent.height`
4. Branch on capturable count:
   - 0 capturable → return as normal (uncapturable opponents coexist)
   - 1 capturable → auto-capture via existing `resolve_capture`
   - 2+ capturable → store `PendingCapture` on turn, set `current_event = CAPTURE_CHOICE`, emit `AwaitingCaptureChoice`, return without capturing

### process_capture_choice rewrite (captures.py)

Change return type from `CollisionResult` to `ProcessResult`. Full implementation:

1. Read `pending_capture` from `state.current_turn`
2. Validate choice string is in `pending_capture.capturable_targets` — if not, return failure
3. Parse `"{player_id}:{stack_id}"` to find target player and stack
4. Execute capture via existing `resolve_capture`
5. Grant extra rolls via existing `grant_extra_rolls(state, captured_height)`
6. Clear `pending_capture` from turn
7. Resume post-move flow — hand off to existing remaining-rolls / extra-rolls / turn-end logic in `process_after_move`

### process.py dispatch fix

Remove `CollisionResult` handling. `process_capture_choice` now returns `ProcessResult` directly, so the dispatch is clean — no special wrapping needed.

## Files Changed

| File | Change |
|---|---|
| `app/schemas/game_engine.py` | Add `PendingCapture`, add field to `Turn` |
| `app/services/game/engine/captures.py` | Rewrite `process_capture_choice` (stub → full, returns `ProcessResult`) |
| `app/services/game/engine/movement.py` | Refactor `handle_road_collision` to partition stacking/opponent, branch on capturable count |
| `app/services/game/engine/process.py` | Fix dispatch for `CaptureChoiceAction` |

## What We're NOT Changing

- `AwaitingCaptureChoice` event schema (already correct)
- `CaptureChoiceAction` action schema (already correct)
- Validation in `validation.py` (already gates on `CAPTURE_CHOICE`)
- Tests (5 failing tests already encode the target behavior)

## Choice Format

Target choice uses string format `"{player_id}:{stack_id}"` — flat, simple, matches existing test expectations. The `AwaitingCaptureChoice.options` list uses the same format.
