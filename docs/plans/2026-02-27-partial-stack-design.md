# Partial Stack Movement Design

## Context

The backend is transitioning from a Token+Stack dual model to a unified Stack-only model where every piece is a `Stack` with a `height`. Partial stack movements (splitting a stack and moving part of it) are a core gameplay mechanic and the main selling point of Ludo Stacked. This design establishes a consistent strategy for stack IDs, splitting, merging, events, and frontend consumption.

## Stack ID System

### Format

Stack IDs encode their composition using underscore-separated component numbers prefixed with `stack_`:

```
stack_1          # individual piece (height 1)
stack_1_2        # two pieces merged (height 2)
stack_1_2_3_4    # all four merged (height 4)
```

### Initialization

Each player starts with 4 stacks in HELL:

```
stack_1, stack_2, stack_3, stack_4
```

All height=1, state=HELL, progress=0.

### Merge Rule

When two stacks land on the same square (same player), their component numbers combine sorted ascending:

- `stack_1` + `stack_3` = `stack_1_3`
- `stack_2` + `stack_1_3` = `stack_1_2_3`
- `stack_4` + `stack_1_2_3` = `stack_1_2_3_4`

Order of arrival does not matter: `stack_1` landing on `stack_3` produces the same result as `stack_3` landing on `stack_1`.

### Split Rule

When splitting a stack, the largest component numbers always peel off the top:

- `stack_1_2_3` split 1 off: moving=`stack_3`, remaining=`stack_1_2`
- `stack_1_2_3` split 2 off: moving=`stack_2_3`, remaining=`stack_1`
- `stack_1_2_3_4` split 2 off: moving=`stack_3_4`, remaining=`stack_1_2`

### Capture Decomposition

When a composite stack is captured and sent to HELL, it decomposes back into its individual component stacks:

- `stack_1_2_3` captured: creates `stack_1`, `stack_2`, `stack_3` (all HELL, progress=0)

### Height

Height is always derivable from the stack ID (count the component numbers) but is kept explicitly on the `Stack` model for quick access. It must stay consistent with the ID.

### Properties

- **Deterministic**: A given combination of pieces always produces the same ID.
- **Unique**: `stack_1_2` can only exist once per player.
- **Reversible**: A composite ID can always be decomposed back to its original components.
- **No counters**: `Player.next_stack_index` is eliminated. IDs are derived from composition.

## Utility Functions

New module: `app/services/game/engine/stack_utils.py`

- `parse_components(stack_id: str) -> list[int]`: `"stack_1_2_3"` -> `[1, 2, 3]`
- `build_stack_id(components: list[int]) -> str`: `[1, 2, 3]` -> `"stack_1_2_3"` (sorts ascending)
- `find_parent_stack(player: Player, move_id: str) -> Stack | None`: finds the existing stack whose components are a superset of the move ID's components
- `get_split_result(parent_id: str, move_id: str) -> tuple[str, str]`: returns `(remaining_id, moving_id)` by subtracting move components from parent components

## Schema Changes

### Stack Model (no field changes)

```python
class Stack(BaseModel):
    stack_id: str       # "stack_1_2_3"
    state: StackState   # HELL, ROAD, HOMESTRETCH, HEAVEN
    height: int = 1     # must match len(parse_components(stack_id))
    progress: int
```

### Player Model

```python
class Player(PlayerAttributes):
    stacks: list[Stack]
    turn_order: int
    abs_starting_index: int
    # next_stack_index: REMOVED
```

### MoveAction

```python
class MoveAction(BaseModel):
    action_type: Literal["move"] = "move"
    stack_id: str    # was token_or_stack_id
```

### New: LegalMoveGroup

```python
class LegalMoveGroup(BaseModel):
    stack_id: str         # existing parent stack
    moves: list[str]      # valid move IDs (full stack + partial splits)
```

### Turn (no change)

```python
class Turn(BaseModel):
    legal_moves: list[str]  # flat list for validation
    # ["stack_1_2_3", "stack_2_3", "stack_3", "stack_4"]
```

### AwaitingChoice Event

```python
class AwaitingChoice(GameEvent):
    event_type: Literal["awaiting_choice"] = "awaiting_choice"
    player_id: UUID
    legal_moves: list[LegalMoveGroup]  # was list[str]
    roll_to_allocate: int
```

## Legal Moves

### Internal Format (Turn.legal_moves)

Flat `list[str]` containing all valid move IDs. For a player with `stack_1_2_3` on ROAD and `stack_4` in HELL, roll=6:

```python
[
    "stack_1_2_3",   # full stack: 6 % 3 == 0, effective=2
    "stack_2_3",     # split 2: 6 % 2 == 0, effective=3
    "stack_3",       # split 1: 6 % 1 == 0, effective=6
    "stack_4",       # exit hell: 6 is a get-out roll
]
```

Partial move IDs are derived from the stack ID using `parse_components` and `build_stack_id`, replacing the old `:count` format.

### Frontend Format (AwaitingChoice.legal_moves)

Grouped by parent stack:

```json
[
    {
        "stack_id": "stack_1_2_3",
        "moves": ["stack_1_2_3", "stack_2_3", "stack_3"]
    },
    {
        "stack_id": "stack_4",
        "moves": ["stack_4"]
    }
]
```

### Grouping Function

New function `get_legal_move_groups(player, roll, board_setup) -> list[LegalMoveGroup]` wraps `get_legal_moves` and groups results by parent stack.

### Validation

Unchanged complexity: `action.stack_id in state.current_turn.legal_moves` (flat list string lookup).

## Events

No new event types. Existing events cover all scenarios:

### Simple Move (no split)

```
StackMoved(stack_id="stack_4", from_state=ROAD, to_state=ROAD, from_progress=5, to_progress=9, roll_used=4)
```

### Exit Hell

```
StackExitedHell(stack_id="stack_2", roll_used=6)
```

### Reach Heaven

```
StackReachedHeaven(stack_id="stack_3")
```

### Split Move

```
StackUpdate(remove_stacks=[stack_1_2_3], add_stacks=[stack_1, stack_2_3])
StackMoved(stack_id="stack_2_3", from_state=ROAD, to_state=ROAD, from_progress=10, to_progress=13, roll_used=6)
```

### Merge (same player collision)

```
StackUpdate(remove_stacks=[stack_1, stack_3], add_stacks=[stack_1_3])
```

### Capture (height=1)

```
StackCaptured(capturing_stack_id="stack_1_2", captured_stack_id="stack_3", position=15, ...)
```

No StackUpdate needed — the captured stack resets to HELL in place.

### Capture (height>1, decomposition)

```
StackCaptured(capturing_stack_id="stack_1_2", captured_stack_id="stack_3_4", ...)
StackUpdate(player_id=captured_player, remove_stacks=[stack_3_4], add_stacks=[stack_3, stack_4])
```

## Backend Move Resolution

When the frontend sends `MoveAction(stack_id="stack_2_3")`:

1. **Exact match check**: Does the player have a stack with `stack_id == "stack_2_3"`?
   - Yes: full stack move via `apply_stack_move()`
2. **Parent lookup**: Find existing stack whose components are a superset of `[2, 3]`
   - Found `stack_1_2_3`: this is a split move
   - Derive remaining: `[1, 2, 3] - [2, 3]` = `[1]` = `stack_1`
   - Execute `apply_split_move(state, parent=stack_1_2_3, remaining_id="stack_1", moving_id="stack_2_3", roll)`

### Movement Functions

- `apply_token_move()`: **eliminated** — height=1 stacks use `apply_stack_move()`
- `apply_stack_move()`: rewritten for Stack model, uses `height`/`progress` directly
- `apply_partial_stack_move()`: replaced by `apply_split_move()` using deterministic ID resolution
- `handle_road_collision()`: signatures updated to `Stack` only

## Frontend Considerations

### Receiving Legal Moves

The grouped `AwaitingChoice` format lets the frontend:
- Show each stack as a tappable target
- For stacks with multiple moves, show a submenu/slider: "move all", "move top 2", "move top 1"
- For stacks with a single move, act on tap

### Receiving State Changes

The frontend gets:
- `StackUpdate` for structural changes (split, merge, capture decomposition)
- `StackMoved` for position changes

These are sufficient for any animation strategy. The frontend owns how to visually transition between states. It can animate peel-off, dissolve-reform, or any other effect based on the before/after data in the events.

### Sending Moves

The frontend sends a simple string — the chosen move ID from the legal moves list:
```json
{"action_type": "move", "stack_id": "stack_2_3"}
```

## Files Changed

| File | Change |
|------|--------|
| `game_engine.py` | Remove `Player.next_stack_index`, add `LegalMoveGroup` |
| `actions.py` | Rename `MoveAction.token_or_stack_id` -> `stack_id` |
| `events.py` | `AwaitingChoice.legal_moves` type -> `list[LegalMoveGroup]` |
| `stack_utils.py` | **New**: `parse_components`, `build_stack_id`, `find_parent_stack`, `get_split_result` |
| `legal_moves.py` | Sub-stack IDs replace `:count`, add `get_legal_move_groups()` |
| `movement.py` | Full rewrite: remove token functions, add `apply_split_move`, resolve move IDs |
| `captures.py` | `send_to_hell` uses `parse_components` for decomposition, emit `StackUpdate` for height>1 |
| `start_game.py` | Create `stack_1..4` instead of Token objects |
| `process.py` | `check_win_condition` uses `StackState.HEAVEN`, pass `action.stack_id` |
| `validation.py` | `action.token_or_stack_id` -> `action.stack_id` |
| `rolling.py` | Build `AwaitingChoice` with `get_legal_move_groups()` |
| Tests | All updated for new Stack model |
