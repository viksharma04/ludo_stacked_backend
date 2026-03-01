"""Stack movement logic for the Stack-only model.

All pieces are Stacks (height >= 1). Movement includes:
- Full stack moves (apply_stack_move)
- Split moves where a sub-stack peels off (apply_split_move)
- Post-move logic: remaining rolls, extra rolls, turn transitions
"""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GameState,
    PendingCapture,
    Player,
    Stack,
    StackState,
    Turn,
)

from .captures import detect_collisions, get_absolute_position, resolve_capture, resolve_collision
from .events import (
    AnyGameEvent,
    AwaitingCaptureChoice,
    AwaitingChoice,
    RollGranted,
    StackExitedHell,
    StackMoved,
    StackReachedHeaven,
    StackUpdate,
    TurnEnded,
    TurnStarted,
)
from .legal_moves import get_legal_move_groups, get_legal_moves
from .rolling import create_new_turn, get_next_turn_order
from .stack_utils import find_parent_stack, get_split_result, parse_components
from .validation import ProcessResult


def process_move(state: GameState, stack_id: str, roll_value: int | None, player_id: UUID) -> ProcessResult:
    """Process a player's move selection.

    Determines whether this is a full stack move or a split move,
    dispatches accordingly, and runs post-move logic on success.

    Args:
        state: Current game state.
        stack_id: ID of stack (or sub-stack) to move.
        roll_value: Specific roll to use, or None for legacy FIFO fallback.
        player_id: The player making the move.

    Returns:
        ProcessResult with new state and events.
    """
    current_turn = state.current_turn
    if current_turn is None:
        logger.error("process_move called with no active turn")
        return ProcessResult.failure("NO_ACTIVE_TURN", "No active turn")

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

    # Find the current player
    current_player = next(p for p in state.players if p.player_id == current_turn.player_id)

    logger.info(
        "Processing move: player=%s, stack=%s, roll=%d",
        str(player_id)[:8],
        stack_id,
        roll,
    )

    # Exact match check: does the player own a stack with this exact stack_id?
    exact_stack = next(
        (s for s in current_player.stacks if s.stack_id == stack_id), None
    )

    if exact_stack is not None:
        result = apply_stack_move(
            state=state,
            stack_id=stack_id,
            roll=roll,
            player=current_player,
            board_setup=state.board_setup,
        )
    else:
        # Parent lookup: is stack_id a sub-stack of an existing stack?
        parent = find_parent_stack(current_player, stack_id)
        if parent is not None:
            remaining_id, moving_id = get_split_result(parent.stack_id, stack_id)
            result = apply_split_move(
                state=state,
                parent=parent,
                remaining_id=remaining_id,
                moving_id=moving_id,
                roll=roll,
                player=current_player,
                board_setup=state.board_setup,
            )
        else:
            logger.warning("Stack not found and no parent: %s", stack_id)
            return ProcessResult.failure(
                "STACK_NOT_FOUND",
                f"Stack {stack_id} not found",
            )

    if not result.success:
        logger.warning(
            "Move failed: stack=%s, error=%s",
            stack_id,
            result.error_code,
        )
        return result

    # Continue processing remaining rolls or end turn
    if result.state is None:
        logger.error("State lost during move processing")
        return ProcessResult.failure("STATE_LOST", "State lost during move processing")

    # If a capture choice is pending, consume the roll but skip post-move flow
    if result.state.current_event == CurrentEvent.CAPTURE_CHOICE:
        remaining = list(current_turn.rolls_to_allocate)
        remaining.remove(roll)
        updated_turn = result.state.current_turn.model_copy(
            update={"rolls_to_allocate": remaining}
        )
        final_state = result.state.model_copy(update={"current_turn": updated_turn})
        return ProcessResult.ok(final_state, result.events)

    logger.debug("Move applied successfully, processing post-move logic")
    return process_after_move(result.state, result.events, current_turn, roll)


def apply_stack_move(
    state: GameState,
    stack_id: str,
    roll: int,
    player: Player,
    board_setup: BoardSetup,
) -> ProcessResult:
    """Apply movement to an entire stack (any height, including 1).

    Movement rules:
    - HELL: If roll is a valid get-out roll, move to ROAD at progress=0.
    - ROAD/HOMESTRETCH: Roll must be divisible by stack height.
      Effective movement = roll / height. Progress is updated.
      If progress reaches squares_to_win -> HEAVEN.
      If progress reaches squares_to_homestretch -> HOMESTRETCH.

    Args:
        state: Current game state.
        stack_id: ID of the stack to move.
        roll: The dice roll value.
        player: The player moving the stack.
        board_setup: Board configuration.

    Returns:
        ProcessResult with updated state and movement events.
    """
    events: list[AnyGameEvent] = []

    # Find the stack
    stack = next((s for s in player.stacks if s.stack_id == stack_id), None)
    if stack is None:
        logger.warning("Stack not found: %s", stack_id)
        return ProcessResult.failure("STACK_NOT_FOUND", f"Stack {stack_id} not found")

    logger.debug(
        "Applying stack move: stack=%s, height=%d, state=%s, progress=%d, roll=%d",
        stack_id,
        stack.height,
        stack.state.value,
        stack.progress,
        roll,
    )

    from_state = stack.state
    from_progress = stack.progress
    new_state = stack.state
    new_progress = stack.progress

    if stack.state == StackState.HELL:
        # Move from HELL to ROAD
        if roll not in board_setup.get_out_rolls:
            logger.warning(
                "Invalid get-out roll: stack=%s, roll=%d, valid_rolls=%s",
                stack_id,
                roll,
                board_setup.get_out_rolls,
            )
            return ProcessResult.failure(
                "INVALID_GET_OUT_ROLL",
                f"Roll {roll} is not a valid get-out roll",
            )
        new_state = StackState.ROAD
        new_progress = 0
        logger.info(
            "Stack exited hell: stack=%s, player=%s",
            stack_id,
            str(player.player_id)[:8],
        )
        events.append(
            StackExitedHell(player_id=player.player_id, stack_id=stack_id, roll_used=roll)
        )

    elif stack.state in (StackState.ROAD, StackState.HOMESTRETCH):
        if roll % stack.height != 0:
            logger.warning(
                "Invalid stack roll: roll=%d, height=%d (not divisible)",
                roll,
                stack.height,
            )
            return ProcessResult.failure(
                "INVALID_STACK_ROLL",
                f"Roll {roll} not divisible by stack height {stack.height}",
            )

        effective_roll = roll // stack.height
        new_progress = stack.progress + effective_roll
        logger.debug(
            "Effective roll: %d / %d = %d, new_progress=%d",
            roll,
            stack.height,
            effective_roll,
            new_progress,
        )

        if new_progress == board_setup.squares_to_win:
            new_state = StackState.HEAVEN
            logger.info(
                "Stack reached heaven: stack=%s, player=%s",
                stack_id,
                str(player.player_id)[:8],
            )
            events.append(StackReachedHeaven(player_id=player.player_id, stack_id=stack_id))
        elif new_progress >= board_setup.squares_to_homestretch:
            new_state = StackState.HOMESTRETCH
            logger.debug(
                "Stack entered homestretch: stack=%s, progress=%d",
                stack_id,
                new_progress,
            )

        events.append(
            StackMoved(
                player_id=player.player_id,
                stack_id=stack_id,
                from_state=from_state,
                to_state=new_state,
                from_progress=from_progress,
                to_progress=new_progress,
                roll_used=roll,
            )
        )

    # Update the stack in the player's stacks list
    updated_stack = stack.model_copy(update={"state": new_state, "progress": new_progress})
    updated_stacks = [
        updated_stack if s.stack_id == stack_id else s for s in player.stacks
    ]
    updated_player = player.model_copy(update={"stacks": updated_stacks})
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    # Handle collisions on ROAD (not HOMESTRETCH or HEAVEN)
    if new_state == StackState.ROAD:
        logger.debug("Checking for collisions at progress=%d", new_progress)
        collision_result = handle_road_collision(
            updated_state, updated_stack, updated_player, board_setup, events
        )
        if collision_result is not None:
            return collision_result

    logger.debug(
        "Stack move complete: stack=%s, %s->%s, progress=%d->%d",
        stack_id,
        from_state.value,
        new_state.value,
        from_progress,
        new_progress,
    )
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
    """Apply a split move: peel a sub-stack off a parent and move it.

    The parent stack is split into:
    - remaining_stack: stays at parent's position with parent's state
    - moving_stack: moves forward by effective_roll

    Args:
        state: Current game state.
        parent: The parent stack being split.
        remaining_id: Stack ID for the piece staying behind.
        moving_id: Stack ID for the piece being moved.
        roll: The dice roll value.
        player: The player moving the stack.
        board_setup: Board configuration.

    Returns:
        ProcessResult with updated state and movement events.
    """
    events: list[AnyGameEvent] = []

    moving_height = len(parse_components(moving_id))
    remaining_height = len(parse_components(remaining_id))

    logger.debug(
        "Applying split move: parent=%s, moving=%s (height=%d), remaining=%s (height=%d), roll=%d",
        parent.stack_id,
        moving_id,
        moving_height,
        remaining_id,
        remaining_height,
        roll,
    )

    if roll % moving_height != 0:
        logger.warning(
            "Invalid split roll: roll=%d, moving_height=%d (not divisible)",
            roll,
            moving_height,
        )
        return ProcessResult.failure(
            "INVALID_SPLIT_ROLL",
            f"Roll {roll} not divisible by moving height {moving_height}",
        )

    effective_roll = roll // moving_height
    new_progress = parent.progress + effective_roll

    # Determine new state for the moving stack
    moving_state = parent.state
    if new_progress == board_setup.squares_to_win:
        moving_state = StackState.HEAVEN
    elif new_progress >= board_setup.squares_to_homestretch:
        moving_state = StackState.HOMESTRETCH

    # Create the remaining stack (same position/state as parent)
    remaining_stack = Stack(
        stack_id=remaining_id,
        state=parent.state,
        height=remaining_height,
        progress=parent.progress,
    )

    # Create the moving stack (new position)
    moving_stack = Stack(
        stack_id=moving_id,
        state=moving_state,
        height=moving_height,
        progress=new_progress,
    )

    logger.info(
        "Split: parent=%s -> remaining=%s (progress=%d) + moving=%s (progress=%d)",
        parent.stack_id,
        remaining_id,
        parent.progress,
        moving_id,
        new_progress,
    )

    # Emit StackUpdate: remove parent, add remaining + moving
    events.append(
        StackUpdate(
            player_id=player.player_id,
            remove_stacks=[parent],
            add_stacks=[remaining_stack, moving_stack],
        )
    )

    # Emit StackMoved for the moving stack
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

    # If HEAVEN, emit StackReachedHeaven
    if moving_state == StackState.HEAVEN:
        logger.info(
            "Split stack reached heaven: stack=%s, player=%s",
            moving_id,
            str(player.player_id)[:8],
        )
        events.append(StackReachedHeaven(player_id=player.player_id, stack_id=moving_id))

    # Update player's stacks: remove parent, add remaining + moving
    updated_stacks = [s for s in player.stacks if s.stack_id != parent.stack_id]
    updated_stacks.append(remaining_stack)
    updated_stacks.append(moving_stack)

    updated_player = player.model_copy(update={"stacks": updated_stacks})
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    # Handle collisions for moving stack on ROAD
    if moving_state == StackState.ROAD:
        # Get the fresh player from updated state
        fresh_player = next(
            p for p in updated_state.players if p.player_id == player.player_id
        )
        logger.debug("Checking for collisions after split at progress=%d", new_progress)
        collision_result = handle_road_collision(
            updated_state, moving_stack, fresh_player, board_setup, events
        )
        if collision_result is not None:
            return collision_result

    logger.debug(
        "Split move complete: parent=%s, remaining=%s, moving=%s, progress=%d->%d",
        parent.stack_id,
        remaining_id,
        moving_id,
        parent.progress,
        new_progress,
    )
    return ProcessResult.ok(updated_state, events)


def process_after_move(
    state: GameState,
    events: list[AnyGameEvent],
    original_turn: Turn,
    used_roll: int,
) -> ProcessResult:
    """Handle post-move logic: remaining rolls, extra rolls, or turn end.

    Args:
        state: State after the move was applied.
        events: Events generated by the move.
        original_turn: The turn state before the move.
        used_roll: The roll value that was just used.

    Returns:
        ProcessResult with final state and all events.
    """
    current_turn = state.current_turn
    if current_turn is None:
        logger.error("Turn lost during move processing")
        return ProcessResult.failure("NO_ACTIVE_TURN", "Turn lost during move")

    # Remove the used roll
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
            # Reorder so usable roll is first
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
                    player_id=original_turn.player_id,
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
            logger.info(
                "More moves available: player=%s, remaining_roll=%d, legal_moves=%d",
                str(original_turn.player_id)[:8],
                usable_roll,
                len(legal_moves),
            )
            return ProcessResult.ok(new_state, events)

        # No legal moves for any remaining roll
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
    logger.info(
        "Turn ended: previous_player=%s, next_player=%s",
        str(original_turn.player_id)[:8],
        str(next_player.player_id)[:8],
    )
    return ProcessResult.ok(new_state, events)


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
