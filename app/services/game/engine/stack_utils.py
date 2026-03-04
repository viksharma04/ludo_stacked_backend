"""Utility functions for the composition-based stack ID system.

Stack IDs follow a deterministic naming convention:
- "stack_1" = individual piece #1 (height 1)
- "stack_1_2" = pieces 1 and 2 merged (height 2)
- "stack_1_2_3_4" = all four pieces merged (height 4)
- Components are always sorted ascending

Operations:
- Merging: stack_1 + stack_3 -> stack_1_3
- Splitting: largest numbers peel off top.
  stack_1_2_3 split 1 off -> moving=stack_3, remaining=stack_1_2
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.game_engine import Player, Stack


def parse_components(stack_id: str) -> list[int]:
    """Extract component numbers from a stack ID.

    Args:
        stack_id: A stack ID string like "stack_1_2_3".

    Returns:
        List of component integers, e.g. [1, 2, 3].
    """
    parts = stack_id.split("_")
    return [int(p) for p in parts[1:]]


def build_stack_id(components: list[int]) -> str:
    """Construct a stack ID from component numbers, sorted ascending.

    Args:
        components: List of component integers, e.g. [3, 1, 2].

    Returns:
        Stack ID string with components sorted, e.g. "stack_1_2_3".
    """
    return "stack_" + "_".join(str(c) for c in sorted(components))


def get_split_result(parent_id: str, move_id: str) -> tuple[str, str]:
    """Determine the remaining and moving stack IDs after a split.

    Given a parent stack and the ID of the sub-stack being moved,
    computes the ID of the remaining sub-stack.

    Args:
        parent_id: The stack ID being split, e.g. "stack_1_2_3".
        move_id: The sub-stack ID being moved, e.g. "stack_3".

    Returns:
        Tuple of (remaining_id, moving_id).
    """
    parent_components = set(parse_components(parent_id))
    move_components = set(parse_components(move_id))
    remaining_components = parent_components - move_components
    return build_stack_id(sorted(remaining_components)), move_id


def find_parent_stack(player: Player, move_id: str) -> Stack | None:
    """Find an existing stack whose components are a strict superset of move_id's.

    Used to detect when a move targets a sub-stack that requires splitting
    from a larger parent stack.

    Args:
        player: The player whose stacks to search.
        move_id: The stack ID to find a parent for.

    Returns:
        The parent Stack if found, or None if move_id exactly matches
        a stack or no parent exists.
    """
    move_components = set(parse_components(move_id))
    for stack in player.stacks:
        stack_components = set(parse_components(stack.stack_id))
        if move_components < stack_components:  # strict subset
            return stack
    return None
