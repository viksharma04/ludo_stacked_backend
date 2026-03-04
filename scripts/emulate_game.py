#!/usr/bin/env python3
"""Interactive game emulation using the core engine.

Runs a full 4-player Ludo Stacked game in the terminal. All player
decisions are made automatically (random). Press space/enter to
advance one action at a time, q to quit.

Usage:
    uv run python scripts/emulate_game.py
"""

import os
import random
import sys
import termios
import tty
from uuid import uuid4

# Add project root to path so we can import the engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.game_engine import (
    CurrentEvent,
    GamePhase,
    GameSettings,
    GameState,
    PlayerAttributes,
    StackState,
)
from app.services.game.engine.actions import (
    CaptureChoiceAction,
    MoveAction,
    RollAction,
    StartGameAction,
)
from app.services.game.engine.events import (
    AwaitingCaptureChoice,
    AwaitingChoice,
    DiceRolled,
    GameEnded,
    GameStarted,
    RollGranted,
    StackCaptured,
    StackExitedHell,
    StackMoved,
    StackReachedHeaven,
    StackUpdate,
    ThreeSixesPenalty,
    TurnEnded,
    TurnStarted,
)
from app.services.game.engine.process import process_action
from app.services.game.start_game import initialize_game

# ── Colors ────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
WHITE = "\033[37m"
BG_DIM = "\033[48;5;236m"

PLAYER_COLORS = {
    "red": RED,
    "blue": BLUE,
    "green": GREEN,
    "yellow": YELLOW,
}

PLAYER_LABELS = {
    "red": "Red",
    "blue": "Blue",
    "green": "Green",
    "yellow": "Yellow",
}


# ── Input handling ────────────────────────────────────────────────────


def get_key():
    """Read a single keypress in raw terminal mode."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def wait_for_advance():
    """Wait for space, enter, or q."""
    while True:
        ch = get_key()
        if ch in (" ", "\r", "\n"):
            return True
        if ch in ("q", "Q", "\x03"):  # q or Ctrl+C
            return False


# ── Display ───────────────────────────────────────────────────────────


def format_stack(stack) -> str:
    """Format a single stack for display."""
    if stack.state == StackState.HELL:
        return f"{DIM}\u00b7H{RESET}"
    elif stack.state == StackState.HEAVEN:
        return f"{CYAN}\u2605{RESET}"
    elif stack.state == StackState.HOMESTRETCH:
        label = f"S{stack.progress}"
        if stack.height > 1:
            label += f"\u00d7{stack.height}"
        return f"{MAGENTA}{label}{RESET}"
    else:  # ROAD
        label = f"R{stack.progress}"
        if stack.height > 1:
            label += f"\u00d7{stack.height}"
        return f"{WHITE}{label}{RESET}"


def format_event(event, state: GameState) -> str:
    """Format a single event for display."""
    player_name = _player_name(event, state)

    if isinstance(event, GameStarted):
        return f"{BOLD}Game started!{RESET}"
    elif isinstance(event, TurnStarted):
        color = _player_color_code(event.player_id, state)
        return f"{color}── {player_name}'s turn ──{RESET}"
    elif isinstance(event, RollGranted):
        reason_map = {
            "turn_start": "turn start",
            "rolled_six": "rolled a 6!",
            "capture_bonus": "capture bonus!",
        }
        return f"  {DIM}roll granted: {reason_map.get(event.reason, event.reason)}{RESET}"
    elif isinstance(event, DiceRolled):
        extra = " \u2192 extra roll!" if event.grants_extra_roll else ""
        return f"  {BOLD}\U0001f3b2 {player_name} rolled {event.value}{RESET}{extra}"
    elif isinstance(event, ThreeSixesPenalty):
        return f"  {RED}\u26a0 Three sixes! {player_name} loses turn{RESET}"
    elif isinstance(event, StackExitedHell):
        return f"  {GREEN}\u2191 {player_name} {event.stack_id} exits Hell{RESET}"
    elif isinstance(event, StackMoved):
        return f"  {WHITE}\u2192 {player_name} {event.stack_id}: {event.from_state.value}@{event.from_progress} \u2192 {event.to_state.value}@{event.to_progress}{RESET}"
    elif isinstance(event, StackReachedHeaven):
        return f"  {CYAN}\u2605 {player_name} {event.stack_id} reached Heaven!{RESET}"
    elif isinstance(event, StackCaptured):
        captor = _name_by_id(event.capturing_player_id, state)
        victim = _name_by_id(event.captured_player_id, state)
        return f"  {RED}\u2694 {captor} captures {victim}'s {event.captured_stack_id} at pos {event.position}!{RESET}"
    elif isinstance(event, StackUpdate):
        added = ", ".join(f"{s.stack_id}(h={s.height})" for s in event.add_stacks)
        removed = ", ".join(s.stack_id for s in event.remove_stacks)
        parts = []
        if removed:
            parts.append(f"-[{removed}]")
        if added:
            parts.append(f"+[{added}]")
        return f"  {DIM}\u21c4 {player_name} stacks: {' '.join(parts)}{RESET}"
    elif isinstance(event, AwaitingChoice):
        parts = []
        for rmg in event.available_moves:
            moves = [m for g in rmg.move_groups for m in g.moves]
            parts.append(f"roll {rmg.roll}: {', '.join(moves)}")
        return f"  {DIM}legal moves \u2014 {' | '.join(parts)}{RESET}"
    elif isinstance(event, AwaitingCaptureChoice):
        return f"  {YELLOW}capture choice: {', '.join(event.options)}{RESET}"
    elif isinstance(event, TurnEnded):
        return f"  {DIM}turn ended: {event.reason}{RESET}"
    elif isinstance(event, GameEnded):
        winner = _name_by_id(event.winner_id, state)
        return f"  {BOLD}{CYAN}\U0001f3c6 {winner} wins the game!{RESET}"
    else:
        return f"  {DIM}[{event.event_type}]{RESET}"


def _player_name(event, state: GameState) -> str:
    """Get player name from an event's player_id."""
    pid = getattr(event, "player_id", None)
    if pid is None:
        return "?"
    return _name_by_id(pid, state)


def _name_by_id(player_id, state: GameState) -> str:
    """Get colored player name by ID."""
    for p in state.players:
        if p.player_id == player_id:
            color = PLAYER_COLORS.get(p.color, WHITE)
            label = PLAYER_LABELS.get(p.color, p.name)
            return f"{color}{label}{RESET}"
    return "?"


def _player_color_code(player_id, state: GameState) -> str:
    for p in state.players:
        if p.player_id == player_id:
            return PLAYER_COLORS.get(p.color, WHITE)
    return WHITE


def render_board(state: GameState) -> str:
    """Render the compact board table."""
    lines = []
    lines.append(f"  {DIM}\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u252c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510{RESET}")

    current_pid = state.current_turn.player_id if state.current_turn else None

    for player in sorted(state.players, key=lambda p: p.turn_order):
        color = PLAYER_COLORS.get(player.color, WHITE)
        label = PLAYER_LABELS.get(player.color, player.name)
        is_current = player.player_id == current_pid
        marker = f"{BOLD}\u25ba" if is_current else " "

        stacks_str = " ".join(format_stack(s) for s in sorted(player.stacks, key=lambda s: s.stack_id))

        # Pad label to 8 chars (accounting for color codes)
        row = f"  {DIM}\u2502{RESET}{marker}{color}{label:<8}{RESET}{DIM}\u2502{RESET} {stacks_str}"
        # Add closing border with padding
        # We need to calculate visible length for padding
        visible_stacks = " ".join(_visible_stack(s) for s in sorted(player.stacks, key=lambda s: s.stack_id))
        pad_needed = 39 - len(visible_stacks)
        if pad_needed > 0:
            row += " " * pad_needed
        row += f"{DIM}\u2502{RESET}"
        lines.append(row)

    lines.append(f"  {DIM}\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518{RESET}")
    return "\n".join(lines)


def _visible_stack(stack) -> str:
    """Return the visible-length version of a stack label (no ANSI)."""
    if stack.state == StackState.HELL:
        return "\u00b7H"
    elif stack.state == StackState.HEAVEN:
        return "\u2605"
    elif stack.state == StackState.HOMESTRETCH:
        label = f"S{stack.progress}"
        if stack.height > 1:
            label += f"\u00d7{stack.height}"
        return label
    else:
        label = f"R{stack.progress}"
        if stack.height > 1:
            label += f"\u00d7{stack.height}"
        return label


def render_status(state: GameState) -> str:
    """Render the turn status line."""
    if state.phase == GamePhase.FINISHED:
        return f"  {BOLD}{CYAN}Game Over!{RESET}"
    if state.current_turn is None:
        return f"  {DIM}Waiting to start...{RESET}"

    turn = state.current_turn
    player_name = _name_by_id(turn.player_id, state)
    event_label = state.current_event.value.upper()
    rolls = turn.rolls_to_allocate
    extra = f" +{turn.extra_rolls} extra" if turn.extra_rolls > 0 else ""

    return f"  Turn: {player_name} {DIM}| {event_label} | Rolls: {rolls}{extra}{RESET}"


def display(state: GameState, events: list, action_desc: str, action_num: int):
    """Clear screen and render full display."""
    os.system("clear")
    print()
    print(f"  {BOLD}Ludo Stacked \u2014 Game Emulation{RESET}    {DIM}action #{action_num}{RESET}")
    print()

    # Action header
    print(f"  {BOLD}{action_desc}{RESET}")
    print()

    # Events
    for event in events:
        print(format_event(event, state))
    print()

    # Board
    print(render_board(state))
    print()

    # Status
    print(render_status(state))
    print()
    print(f"  {DIM}[space] next action  [q] quit{RESET}")


# ── Auto-decision logic ──────────────────────────────────────────────


def auto_roll() -> RollAction:
    """Generate a random dice roll."""
    return RollAction(value=random.randint(1, 6))


def auto_move(state: GameState) -> MoveAction:
    """Pick a random legal move from the available rolls."""
    turn = state.current_turn
    if not turn or not turn.rolls_to_allocate or not turn.legal_moves:
        return MoveAction(stack_id="stack_1", roll_value=1)

    # Pick a random roll, then a random legal move for that roll
    from app.services.game.engine.legal_moves import get_legal_moves

    player = next(p for p in state.players if p.player_id == turn.player_id)
    usable = []
    for roll in turn.rolls_to_allocate:
        moves = get_legal_moves(player, roll, state.board_setup)
        if moves:
            usable.append((roll, moves))
    if not usable:
        choice = random.choice(turn.legal_moves)
        return MoveAction(stack_id=choice, roll_value=turn.rolls_to_allocate[0])

    roll, moves = random.choice(usable)
    return MoveAction(stack_id=random.choice(moves), roll_value=roll)


def auto_capture_choice(state: GameState) -> CaptureChoiceAction:
    """Pick a random capture target from pending options."""
    turn = state.current_turn
    if turn and turn.pending_capture:
        choice = random.choice(turn.pending_capture.capturable_targets)
        return CaptureChoiceAction(choice=choice)
    # Fallback
    return CaptureChoiceAction(choice="")


# ── Main loop ─────────────────────────────────────────────────────────


def create_game() -> GameState:
    """Initialize a fresh 4-player game."""
    settings = GameSettings(
        num_players=4,
        player_attributes=[
            PlayerAttributes(player_id=uuid4(), name="Player 1", color="red"),
            PlayerAttributes(player_id=uuid4(), name="Player 2", color="blue"),
            PlayerAttributes(player_id=uuid4(), name="Player 3", color="green"),
            PlayerAttributes(player_id=uuid4(), name="Player 4", color="yellow"),
        ],
        grid_length=6,
    )
    return initialize_game(settings)


def run():
    """Main emulation loop."""
    state = create_game()
    action_num = 0

    # Start the game
    action_num += 1
    result = process_action(state, StartGameAction(), state.players[0].player_id)
    if not result.success:
        print(f"Failed to start game: {result.error_message}")
        return
    state = result.state
    display(state, result.events, "Start Game", action_num)

    if not wait_for_advance():
        return

    # Game loop
    while state.phase != GamePhase.FINISHED:
        turn = state.current_turn
        if turn is None:
            break

        player_id = turn.player_id
        player_name = _name_by_id(player_id, state)

        # Decide action based on current_event
        if state.current_event == CurrentEvent.PLAYER_ROLL:
            action = auto_roll()
            action_desc = f"\U0001f3b2 {player_name} rolls..."

        elif state.current_event == CurrentEvent.PLAYER_CHOICE:
            action = auto_move(state)
            action_desc = f"\u2192 {player_name} moves {action.stack_id} (roll={action.roll_value})"

        elif state.current_event == CurrentEvent.CAPTURE_CHOICE:
            action = auto_capture_choice(state)
            action_desc = f"\u2694 {player_name} chooses capture target"

        else:
            break

        # Process the action
        action_num += 1
        result = process_action(state, action, player_id)

        if not result.success:
            # Display the error, then continue (engine should recover)
            display(state, [], f"\u26a0 Error: {result.error_message}", action_num)
            if not wait_for_advance():
                return
            continue

        state = result.state
        display(state, result.events, action_desc, action_num)

        # Check for win
        from app.services.game.engine.process import check_win_condition

        winner = check_win_condition(state)
        if winner:
            winner_name = _name_by_id(winner, state)
            print()
            print(f"  {BOLD}{CYAN}\U0001f3c6\U0001f3c6\U0001f3c6 {winner_name} wins the game! \U0001f3c6\U0001f3c6\U0001f3c6{RESET}")
            print()
            print(f"  {DIM}Game finished in {action_num} actions.{RESET}")
            print(f"  {DIM}Press any key to exit.{RESET}")
            get_key()
            return

        if not wait_for_advance():
            return

    print()
    print(f"  {DIM}Game ended after {action_num} actions.{RESET}")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print(f"\n  {DIM}Interrupted.{RESET}")
