# Core Engine Test Suite Design

Date: 2026-02-28

## Purpose

Comprehensive test suite to validate the core Ludo Stacked game engine is complete and correct. Tests encode **intended game rules** — failing tests become the implementation backlog.

## Key Game Rules (Confirmed with Owner)

### Dice Rolling
- Rolling 6 grants extra roll (stay in PLAYER_ROLL)
- Three consecutive 6s = penalty (turn ends, no moves applied since player never left PLAYER_ROLL)
- Last three rolls checked for penalty (not just first three)
- **Player chooses roll order** (not FIFO) — current code uses `rolls[0]`, needs change
- **Skip roll if no legal moves, try next roll** — current code ends turn immediately, needs change

### Movement
- Must move if legal moves exist (no passing)
- Full flexibility: any roll can be applied to any eligible stack, including one that just moved
- Exit HELL with get_out_roll (default [6]), land at ROAD progress=0
- Roll must be divisible by stack height; effective_roll = roll / height
- Cannot overshoot heaven; exact roll required

### Stacking
- Own stacks merge everywhere (ROAD and HOMESTRETCH)
- Composition-based IDs: components combine sorted ascending
- Only height=1 stacks can exit HELL (captured stacks always decomposed)
- Split: largest components peel off

### Captures
- Only on ROAD (homestretch is private per player)
- Height comparison: capturing >= captured → capture succeeds
- Smaller landing on larger → nothing happens (coexist)
- Safe spaces prevent all captures
- Captured stacks sent to HELL (height>1 decomposed to individuals)
- Capture grants extra_rolls = captured_height
- **Capture chains accumulate** — extra rolls from further captures stack
- **Capture choice** — when multiple opponents at same position, player chooses target

### Board Geometry (grid_length = g)
- step = 2g + 1 (distance between starting positions)
- starting_positions = [0, step, 2*step, 3*step]
- squares_to_homestretch = 8g + 2 (current code has 8g+1 — BUG)
- squares_to_win = 9g + 1
- homestretch_length = g - 1
- safe_offset from each start = 2g - 2
- safe_spaces = all 8 safe spaces always present (independent of player count)
- **2 players use opposite corners**: positions 0 and 2*step (1st and 3rd)
- **3 players use first three**: positions 0, step, 2*step

### Game End
- Win when ALL of a player's stacks are in HEAVEN
- Just detect winner for now — no rankings or continued play

## Fixture Updates Required

Current `conftest.py` fixtures are wrong for grid_length=6:

| Field | Current (wrong) | Correct (g=6) |
|-------|-----------------|----------------|
| squares_to_win | 57 | 55 |
| squares_to_homestretch | 52 | 50 |
| safe_spaces | [0,8,13,21,26,34,39,47] | [0,10,13,23,26,36,39,49] |

Two-player fixture:
- starting_positions should be [0, 26] (opposite corners) ✓ (already correct)
- safe_spaces should be all 8 (currently [0, 26] — BUG)

## Test Files

### 1. test_multi_roll_allocation.py (NEW)
Tests for player roll choice and skip-no-moves behavior.

1. Player can choose which roll to use (not forced FIFO)
2. Roll order flexibility — legal moves calculated for all accumulated rolls
3. Remaining rolls after using one from the middle
4. Skip roll with no legal moves, try next roll
5. All rolls have no legal moves → turn ends
6. Exit HELL with 6, then move same stack with remaining roll
7. Multiple moves in one turn using different rolls

### 2. test_hell_exit_collisions.py (NEW)
Tests for HELL exit interactions.

1. Exit to empty starting position
2. Exit when own stack at starting position → merge
3. Exit when opponent at starting position → safe space, no capture
4. Exit when own multi-height stack at starting position → merge into taller stack
5. Multiple stacks exit in same turn (roll [6, 6, non-6])
6. Exit and merge emits correct events (StackExitedHell + StackUpdate)

### 3. test_capture_chains.py (NEW)
Tests for capture snowball mechanics.

1. Single capture grants extra rolls = captured height
2. Extra roll from capture leads to another capture → more bonus rolls
3. Extra rolls accumulate across multiple captures
4. Extra rolls used after all allocated rolls consumed
5. Capture bonus emits RollGranted with reason="capture_bonus"
6. Extra roll of 6 grants another roll on top
7. Extra roll with no legal moves → turn ends

### 4. test_capture_choice.py (NEW)
Tests for multi-target capture selection.

1. Single opponent at position → auto-resolved, no choice needed
2. Multiple opponents at same position → AwaitingCaptureChoice emitted
3. Player selects target → CaptureChoiceAction resolves correctly
4. Options only include capturable stacks (height <=)
5. Unchosen opponents remain on the square
6. Capture choice grants extra rolls
7. Invalid capture choice rejected

### 5. test_homestretch_heaven.py (NEW)
Tests for endgame path.

1. Stack enters homestretch at exact boundary (progress reaches squares_to_homestretch)
2. Stack progresses through homestretch
3. Stack reaches heaven with exact roll (progress == squares_to_win)
4. Cannot overshoot heaven
5. Stacking in homestretch (own stacks merge)
6. Merged stack in homestretch moves (roll divisible by height)
7. Split move in homestretch — partial to heaven
8. Homestretch is private (no opponent collisions)
9. Win detection after last stack reaches heaven
10. No win when some stacks still on road

### 6. test_full_turn_flow.py (NEW)
Integration tests through process_action().

1. Complete basic turn — all in HELL, non-6 → turn passes
2. Exit HELL then move — roll 6 → exit → roll 4 → advance
3. Roll [6, 6, non-6] — double exit + move
4. Three sixes penalty flow
5. Capture during turn → extra roll → continue
6. Full game start sequence events
7. Turn wraps around (4 players)
8. Multiple actions in a turn sequence

### 7. test_stacking.py (additions)
Edge cases for stacking.

1. Three-way merge
2. Split then re-merge
3. Maximum stack size (height=4, all components)
4. Height-4 stack movement (divisibility constraints)
5. Stack captured then rebuilt
6. Stacking on homestretch
7. Split stack event ordering (StackUpdate before StackMoved)

### 8. test_board_geometry.py (NEW)
Board setup formula verification.

1. Board formulas for grid_length=5: verify all values
2. Board formulas for grid_length=6: verify all values
3. Absolute position wrapping
4. Different players at same absolute position
5. All safe spaces prevent capture
6. Starting positions are in safe_spaces
7. Homestretch boundary (last ROAD vs first HOMESTRETCH)
8. Board always has all 8 safe spaces regardless of player count
9. 2-player placement: opposite corners (1st and 3rd starting position)
10. 3-player placement: first three starting positions

## Bugs to Surface

Tests will intentionally fail against current code for these known issues:
1. `squares_to_homestretch` formula: `8g+1` → should be `8g+2`
2. Test fixtures: wrong values for g=6
3. Roll allocation: FIFO → should be player choice
4. No-legal-moves handling: ends turn → should skip to next roll
5. 2-player safe_spaces: only [0, 26] → should be all 8
6. Capture choice: placeholder → needs implementation

## Estimated Test Count

~59 new test scenarios across 8 files, bringing total from 93 to ~152.
