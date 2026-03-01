"""Legal move calculation for stacks."""

import logging

from app.schemas.game_engine import BoardSetup, LegalMoveGroup, Player, RollMoveGroup, StackState

from .stack_utils import build_stack_id, parse_components

logger = logging.getLogger(__name__)


def get_legal_moves(player: Player, roll: int, board_setup: BoardSetup) -> list[str]:
    """Determine legal moves for a player given a roll.

    Returns stack IDs (including sub-stack IDs for partial moves).
    e.g. ["stack_1_2_3", "stack_2_3", "stack_3", "stack_4"]
    """
    logger.debug(
        "Calculating legal moves: player=%s, roll=%d",
        str(player.player_id)[:8],
        roll,
    )
    legal_moves: list[str] = []

    for stack in player.stacks:
        if stack.state == StackState.HELL and roll in board_setup.get_out_rolls:
            legal_moves.append(stack.stack_id)

        elif stack.state in (StackState.ROAD, StackState.HOMESTRETCH):
            # Full stack movement
            if roll % stack.height == 0:
                effective_roll = roll // stack.height
                if stack.progress + effective_roll <= board_setup.squares_to_win:
                    legal_moves.append(stack.stack_id)

            # Partial stack movements (only for multi-height stacks)
            if stack.height > 1:
                components = parse_components(stack.stack_id)
                for partial_count in range(1, stack.height):
                    if roll % partial_count == 0:
                        effective_roll = roll // partial_count
                        if stack.progress + effective_roll <= board_setup.squares_to_win:
                            # Build sub-stack ID from the largest components
                            moving_components = components[-partial_count:]
                            move_id = build_stack_id(moving_components)
                            legal_moves.append(move_id)

    logger.debug(
        "Legal moves calculated: player=%s, roll=%d, count=%d, moves=%s",
        str(player.player_id)[:8],
        roll,
        len(legal_moves),
        legal_moves,
    )
    return legal_moves


def get_legal_move_groups(
    player: Player, roll: int, board_setup: BoardSetup
) -> list[LegalMoveGroup]:
    """Get legal moves grouped by parent stack for frontend consumption."""
    flat_moves = get_legal_moves(player, roll, board_setup)

    groups: dict[str, list[str]] = {}
    for move_id in flat_moves:
        parent = None
        for stack in player.stacks:
            if move_id == stack.stack_id:
                parent = stack.stack_id
                break
            move_comps = set(parse_components(move_id))
            stack_comps = set(parse_components(stack.stack_id))
            if move_comps < stack_comps:
                parent = stack.stack_id
                break

        if parent is None:
            parent = move_id

        if parent not in groups:
            groups[parent] = []
        groups[parent].append(move_id)

    return [LegalMoveGroup(stack_id=stack_id, moves=moves) for stack_id, moves in groups.items()]


def get_all_roll_move_groups(
    player: Player, rolls: list[int], board_setup: BoardSetup
) -> list[RollMoveGroup]:
    """Compute legal move groups for all rolls, excluding rolls with no moves.

    Deduplicates roll values (e.g. [6, 6, 3] produces entries for 6 and 3, not two 6s).
    Returns only rolls that have at least one legal move.
    """
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


def has_any_legal_moves(player: Player, roll: int, board_setup: BoardSetup) -> bool:
    """Quick check if player has any legal moves."""
    for stack in player.stacks:
        if stack.state == StackState.HELL and roll in board_setup.get_out_rolls:
            return True

        if stack.state in (StackState.ROAD, StackState.HOMESTRETCH):
            if roll % stack.height == 0:
                effective_roll = roll // stack.height
                if stack.progress + effective_roll <= board_setup.squares_to_win:
                    return True

            if stack.height > 1:
                for partial_count in range(1, stack.height):
                    if roll % partial_count == 0:
                        effective_roll = roll // partial_count
                        if stack.progress + effective_roll <= board_setup.squares_to_win:
                            return True

    return False
