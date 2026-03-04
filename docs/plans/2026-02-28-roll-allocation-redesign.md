# Roll Allocation Redesign

## Problem

The current roll allocation is sequential: the engine picks the first usable roll from `rolls_to_allocate` and presents moves for only that roll. The player has no choice over which roll to use. This is wrong — the player should see legal moves for ALL accumulated rolls and choose which `(roll, stack)` pair to use.

## Design Decisions

All confirmed with the user during brainstorming.

### Rolling Phase — Unchanged

Player rolls, 6 grants extra roll, non-6 ends rolling phase. Rolls accumulate in `rolls_to_allocate`. Three consecutive 6s trigger penalty. No changes here.

### Choice Phase — Combined View

When transitioning to `PLAYER_CHOICE`, the engine computes legal moves for **every** accumulated roll and presents them all in a single `AwaitingChoice` event. The structure is grouped by roll, then by parent stack within each roll:

```
AwaitingChoice:
  available_moves: [
    { roll: 6, move_groups: [
        { stack_id: "stack_1", moves: ["stack_1"] },
        { stack_id: "stack_2_3", moves: ["stack_2_3", "stack_3"] }
    ]},
    { roll: 4, move_groups: [
        { stack_id: "stack_2_3", moves: ["stack_2_3", "stack_3"] }
    ]}
  ]
```

Rolls with no legal moves are excluded from `available_moves` (silently discarded).

### MoveAction Gets `roll_value`

`MoveAction` gains a `roll_value: int` field. The player explicitly says "move stack_1 using roll 6." The engine validates:

1. `roll_value` exists in `rolls_to_allocate`
2. `stack_id` is a legal move for that `roll_value`

If either check fails, return an error. State is unchanged — player retries.

### Roll Consumption

`rolls_to_allocate.remove(roll_value)` — removes the first occurrence. This is correct even for duplicate values (e.g. two 6s) since identical rolls produce identical legal moves.

### Recompute After Every Move

After each move is processed, the engine recomputes legal moves for ALL remaining rolls against the **new** board state. A fresh `AwaitingChoice` is emitted. This handles cases like:

- Stack exits HELL with roll 6, now a remaining roll 4 can move that stack on ROAD
- Stack merges after landing, changing which rolls are divisible by the new height

### Bonus Rolls After Remaining Rolls

When a capture grants `extra_rolls`, the bonus is deferred until all accumulated rolls are consumed. Flow:

```
rolls=[6, 4], player uses 6, captures -> extra_rolls += 1
-> AwaitingChoice for remaining [4]
-> player uses 4
-> NOW enter PLAYER_ROLL for capture bonus
```

This is already the behavior in `process_after_move` — it checks `remaining_rolls` before `extra_rolls`.

### HELL Exit Merges Are Immediately Usable

A stack that exits HELL and merges with a friendly stack at the starting position is available for remaining rolls in the same turn.

### Turn End Conditions

Turn ends when:
- All rolls consumed and no extra rolls remain → `TurnEnded(reason="all_rolls_used")`
- No remaining roll has any legal moves (after recomputation) → `TurnEnded(reason="no_legal_moves")`
- Three sixes penalty → `TurnEnded(reason="three_sixes")`

## Schema Changes

### New Model: `RollMoveGroup`

```python
class RollMoveGroup(BaseModel):
    roll: int
    move_groups: list[LegalMoveGroup]
```

### Updated: `AwaitingChoice`

```python
class AwaitingChoice(GameEvent):
    event_type: Literal["awaiting_choice"] = "awaiting_choice"
    player_id: UUID
    available_moves: list[RollMoveGroup]
    # REMOVED: roll_to_allocate: int
    # REMOVED: legal_moves: list[LegalMoveGroup]
```

### Updated: `MoveAction`

```python
class MoveAction(BaseModel):
    action_type: Literal["move"] = "move"
    stack_id: str
    roll_value: int  # NEW
```

### Updated: `Turn`

`Turn.legal_moves: list[str]` may need updating since it currently stores a flat list for a single roll. With multi-roll, this should store the union of all legal moves across all rolls (used for validation in `process_move`).

## Engine Changes

### `rolling.py` — `process_roll()`

After rolling phase ends (non-6 rolled), compute `RollMoveGroup` for each roll in `rolls_to_allocate`. Filter out rolls with no legal moves. If any roll has moves, emit `AwaitingChoice` with `available_moves`. If none have moves, end turn.

### `movement.py` — `process_move()`

- Accept `roll_value` from `MoveAction` (passed through from `process.py`)
- Validate `roll_value` is in `rolls_to_allocate`
- Validate `stack_id` is legal for `roll_value`
- Remove `roll_value` from `rolls_to_allocate` (by value, not index)
- Apply the move using `roll_value`

### `movement.py` — `process_after_move()`

- Compute `RollMoveGroup` for each remaining roll against new board state
- Filter out rolls with no legal moves
- If any roll has moves, emit fresh `AwaitingChoice`
- Otherwise check `extra_rolls`, then end turn

### `movement.py` — `resume_after_capture()`

Same pattern as `process_after_move` — compute combined view for remaining rolls.

### `legal_moves.py`

Add helper function:

```python
def get_all_roll_move_groups(
    player: Player, rolls: list[int], board_setup: BoardSetup
) -> list[RollMoveGroup]:
    """Compute legal move groups for all rolls, excluding rolls with no moves."""
```

### `validation.py`

Update move validation to check `roll_value` against `rolls_to_allocate` and `stack_id` against legal moves for that specific roll.

### `process.py`

Pass `action.roll_value` to `process_move()`.
