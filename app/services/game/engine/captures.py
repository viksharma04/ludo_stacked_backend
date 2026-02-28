"""Capture detection and resolution logic."""

import logging
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)

from app.schemas.game_engine import (
    BoardSetup,
    GameState,
    Player,
    Stack,
    StackState,
)

from .events import (
    AnyGameEvent,
    StackCaptured,
    StackUpdate,
)
from .stack_utils import build_stack_id, parse_components
from .validation import ProcessResult


@dataclass
class CollisionResult:
    """Result of resolving a collision."""

    state: GameState | None = None
    events: list[AnyGameEvent] = field(default_factory=list)
    requires_choice: bool = False


def get_absolute_position(
    piece: Stack,
    player: Player,
    board_setup: BoardSetup,
) -> int:
    """Calculate the absolute board position of a token or stack.

    Args:
        piece: Stack to get position for.
        player: The player who owns the piece.
        board_setup: Board configuration.

    Returns:
        Absolute position on the shared road (0 to squares_to_homestretch-1).
    """
    progress = piece.progress

    abs_pos = (player.abs_starting_index + progress) % board_setup.squares_to_homestretch
    logger.debug(
        "Absolute position: piece=%s, player_start=%d, progress=%d, abs_pos=%d",
        piece.stack_id,
        player.abs_starting_index,
        progress,
        abs_pos,
    )
    return abs_pos


def detect_collisions(
    state: GameState,
    moved_piece: Stack,
    moving_player: Player,
    board_setup: BoardSetup,
) -> list[tuple[Player, Stack]]:
    """Detect all stacks at the same position as the moved piece.

    Only checks stacks on ROAD (not HELL, HOMESTRETCH, or HEAVEN).

    Args:
        state: Current game state.
        moved_piece: The stack that just moved.
        moving_player: The player who moved.
        board_setup: Board configuration.

    Returns:
        List of (player, stack) tuples for all colliding stacks.
    """
    moved_position = get_absolute_position(moved_piece, moving_player, board_setup)
    collisions: list[tuple[Player, Stack]] = []

    moved_id = moved_piece.stack_id
    logger.debug(
        "Detecting collisions: moved_piece=%s, abs_position=%d",
        moved_id,
        moved_position,
    )

    for player in state.players:
        for stack in player.stacks:
            # Skip the moved piece itself
            if stack.stack_id == moved_id and player.player_id == moving_player.player_id:
                continue

            # Only check ROAD stacks
            if stack.state != StackState.ROAD:
                continue

            stack_pos = get_absolute_position(stack, player, board_setup)
            if stack_pos == moved_position:
                logger.debug(
                    "Collision found: stack=%s, player=%s",
                    stack.stack_id,
                    str(player.player_id)[:8],
                )
                collisions.append((player, stack))

    logger.debug("Total collisions detected: %d", len(collisions))
    return collisions


def resolve_collision(
    state: GameState,
    moving_player: Player,
    moving_piece: Stack,
    other_player: Player,
    other_piece: Stack,
    events: list[AnyGameEvent],
) -> CollisionResult:
    """Resolve a collision between two pieces.

    Collision rules:
    - Same player: Form a stack (or merge stacks)
    - Different player: Capture if stack size is smaller

    Args:
        state: Current game state.
        moving_player: Player who just moved.
        moving_piece: The piece that moved.
        other_player: Player who owns the other piece.
        other_piece: The stationary piece.
        events: Events list to append to.

    Returns:
        CollisionResult with updated state and events.
    """
    same_player = moving_player.player_id == other_player.player_id
    logger.debug(
        "Resolving collision: same_player=%s, moving_player=%s, other_player=%s",
        same_player,
        str(moving_player.player_id)[:8],
        str(other_player.player_id)[:8],
    )

    if same_player:
        logger.info(
            "Stacking: player=%s is forming a stack",
            str(moving_player.player_id)[:8],
        )
        return resolve_stacking(state, moving_player, moving_piece, other_piece)
    else:
        # If the current position is a safe space, no capture occurs
        moved_position = get_absolute_position(moving_piece, moving_player, state.board_setup)
        if moved_position in state.board_setup.safe_spaces:
            logger.info(
                "Safe space: no capture at position %d (safe_spaces=%s)",
                moved_position,
                state.board_setup.safe_spaces,
            )
            # Return empty events list - no capture events occur on safe spaces
            # (returning the passed-in events list would cause duplication)
            return CollisionResult(state=state, events=[])

        logger.info(
            "Capture attempt: player=%s attacking player=%s",
            str(moving_player.player_id)[:8],
            str(other_player.player_id)[:8],
        )
        return resolve_capture(
            state, moving_player, moving_piece, other_player, other_piece, events
        )


def resolve_stacking(
    state: GameState,
    player: Player,
    piece1: Stack,
    piece2: Stack,
) -> CollisionResult:
    """Resolve a stacking situation (same player's stacks meet).

    When two stacks combine, the new stack_id is formed by joining the
    component IDs (e.g. stack_1 + stack_2 → stack_1_2) and the height
    is the sum of both heights.

    Args:
        state: Current game state.
        player: The player whose stacks are combining.
        piece1: First stack (the one that moved).
        piece2: Second stack (the stationary one).

    Returns:
        CollisionResult with updated state and StackUpdate event.
    """
    events: list[AnyGameEvent] = []

    # Build combined stack ID from sorted components: e.g. "stack_3" + "stack_1" → "stack_1_3"
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

    # Create the merged stack (keeps position/state of the moved piece)
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

    updated_player = player.model_copy(
        update={
            "stacks": updated_stacks,
        }
    )
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    logger.debug(
        "Stack formed: stack_id=%s, height=%d, progress=%d",
        new_stack_id,
        new_height,
        piece2.progress,
    )
    return CollisionResult(state=updated_state, events=events)


def resolve_capture(
    state: GameState,
    capturing_player: Player,
    capturing_piece: Stack,
    captured_player: Player,
    captured_piece: Stack,
    _events: list[AnyGameEvent],  # Not used; function returns its own events
) -> CollisionResult:
    """Resolve a capture (different players' stacks meet).

    Rules:
    - Moving stack height >= stationary stack height: Stationary stack captured (sent to HELL)
    - Moving stack height < stationary stack height: No capture occurs
    - Capturing grants extra rolls equal to the captured stack's height

    Args:
        state: Current game state.
        capturing_player: Player who moved.
        capturing_piece: The moving stack.
        captured_player: Player being captured.
        captured_piece: The stationary stack.
        _events: Events list (not used; function returns its own events).

    Returns:
        CollisionResult with updated state and capture events.
    """
    new_events: list[AnyGameEvent] = []

    capturing_size = capturing_piece.height
    captured_size = captured_piece.height

    logger.debug(
        "Capture comparison: capturing_size=%d, captured_size=%d",
        capturing_size,
        captured_size,
    )

    position = get_absolute_position(capturing_piece, capturing_player, state.board_setup)
    updated_state = state

    if capturing_size >= captured_size:
        # Capturing piece wins - captured stack goes to HELL
        logger.info(
            "Capture successful: capturing_player=%s captured stack (height=%d) from player=%s at position=%d",
            str(capturing_player.player_id)[:8],
            captured_size,
            str(captured_player.player_id)[:8],
            position,
        )
        updated_state = send_to_hell(updated_state, captured_player, captured_piece)

        new_events.append(
            StackCaptured(
                capturing_player_id=capturing_player.player_id,
                capturing_stack_id=capturing_piece.stack_id,
                captured_player_id=captured_player.player_id,
                captured_stack_id=captured_piece.stack_id,
                position=position,
                grants_extra_roll=True,
            )
        )

        # Grant extra rolls based on captured stack's height
        logger.info(
            "Granting %d extra rolls for capture",
            captured_size,
        )
        updated_state = grant_extra_rolls(updated_state, captured_size)

    elif captured_size > capturing_size:
        # Captured piece is safe - no capture occurs
        logger.info(
            "Capture blocked: captured_size=%d > capturing_size=%d",
            captured_size,
            capturing_size,
        )

    return CollisionResult(state=updated_state, events=new_events)


def send_to_hell(
    state: GameState,
    player: Player,
    captured_stack: Stack,
) -> GameState:
    """Send a captured stack back to HELL.

    For height=1 stacks, resets the stack in place.
    For height>1 stacks, removes the stack and creates individual
    height=1 stacks in HELL.

    Args:
        state: Current game state.
        player: Player whose stack is being sent to HELL.
        captured_stack: The stack being captured.

    Returns:
        Updated game state.
    """
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
        # Remove the multi-height stack, decompose into individual component stacks
        remaining_stacks = [
            s for s in current_player.stacks if s.stack_id != captured_stack.stack_id
        ]
        components = parse_components(captured_stack.stack_id)
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
            update={
                "stacks": [*remaining_stacks, *hell_stacks],
            }
        )

    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    return state.model_copy(update={"players": updated_players})


def grant_extra_rolls(state: GameState, count: int = 1) -> GameState:
    """Grant extra rolls to the current player based on capture size.

    Args:
        state: Current game state.
        count: Number of extra rolls to grant (typically the captured stack size).

    Returns:
        Updated game state with extra_rolls incremented by count.
    """
    if state.current_turn is None:
        logger.warning("Cannot grant extra rolls: no active turn")
        return state

    new_total = state.current_turn.extra_rolls + count
    logger.debug(
        "Granting extra rolls: count=%d, new_total=%d, player=%s",
        count,
        new_total,
        str(state.current_turn.player_id)[:8],
    )
    updated_turn = state.current_turn.model_copy(update={"extra_rolls": new_total})
    return state.model_copy(update={"current_turn": updated_turn})


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

    # Resume post-move flow
    from .movement import resume_after_capture
    return resume_after_capture(state, events)
