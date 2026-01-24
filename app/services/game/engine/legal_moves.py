"""Legal move calculation for tokens and stacks."""

from app.schemas.game_engine import BoardSetup, Player, TokenState


def get_legal_moves(player: Player, roll: int, board_setup: BoardSetup) -> list[str]:
    """Determine legal moves for a player given a roll.

    A move is legal if:
    - Token in HELL and roll is a get-out roll (typically 6)
    - Token on ROAD/HOMESTRETCH and progress + roll <= squares_to_win
    - Stack on ROAD and effective_roll (roll / stack_height) allows movement

    Args:
        player: The player whose tokens/stacks to check.
        roll: The dice roll value.
        board_setup: Board configuration for boundaries.

    Returns:
        List of token_ids and stack_ids that can be legally moved.
    """
    legal_moves: list[str] = []

    # Check individual tokens
    for token in player.tokens:
        # Skip tokens that are in a stack (they move with the stack)
        if token.in_stack:
            continue

        if token.state == TokenState.HELL and roll in board_setup.get_out_rolls:
            legal_moves.append(token.token_id)

        elif token.state in (TokenState.ROAD, TokenState.HOMESTRETCH):
            if token.progress + roll <= board_setup.squares_to_win:
                legal_moves.append(token.token_id)

        # TokenState.HEAVEN - no legal moves (token has finished)

    # Check stacks for legal moves
    if player.stacks:
        for stack in player.stacks:
            stack_height = len(stack.tokens)

            # Get the first token in the stack to check its state/progress
            first_token_id = stack.tokens[0]
            first_token = next(
                (t for t in player.tokens if t.token_id == first_token_id), None
            )
            if first_token is None:
                continue

            # Only ROAD stacks can be moved (HOMESTRETCH stacks would need special handling)
            if first_token.state not in (TokenState.ROAD, TokenState.HOMESTRETCH):
                continue

            # Check full stack movement
            if roll % stack_height == 0:
                effective_roll = roll // stack_height
                if first_token.progress + effective_roll <= board_setup.squares_to_win:
                    legal_moves.append(stack.stack_id)

            # Check partial stack movements (1 to N-1 tokens)
            # Format: stack_id:count means "move count tokens from this stack"
            # Note: count=1 is always valid (roll % 1 == 0), moving a single token
            for partial_count in range(1, stack_height):
                if roll % partial_count == 0:
                    effective_roll = roll // partial_count
                    if first_token.progress + effective_roll <= board_setup.squares_to_win:
                        legal_moves.append(f"{stack.stack_id}:{partial_count}")

    return legal_moves


def has_any_legal_moves(player: Player, roll: int, board_setup: BoardSetup) -> bool:
    """Quick check if player has any legal moves.

    More efficient than get_legal_moves() when you only need to know if moves exist.
    """
    # Check individual tokens
    for token in player.tokens:
        if token.in_stack:
            continue

        if token.state == TokenState.HELL and roll in board_setup.get_out_rolls:
            return True

        if token.state in (TokenState.ROAD, TokenState.HOMESTRETCH):
            if token.progress + roll <= board_setup.squares_to_win:
                return True

    # Check stacks
    if player.stacks:
        for stack in player.stacks:
            stack_height = len(stack.tokens)
            first_token_id = stack.tokens[0]
            first_token = next(
                (t for t in player.tokens if t.token_id == first_token_id), None
            )
            if first_token is None:
                continue

            if first_token.state not in (TokenState.ROAD, TokenState.HOMESTRETCH):
                continue

            # Check full stack movement
            if roll % stack_height == 0:
                effective_roll = roll // stack_height
                if first_token.progress + effective_roll <= board_setup.squares_to_win:
                    return True

            # Check partial stack movements (1 to N-1 tokens)
            # Note: count=1 is always valid, so if progress + roll is valid, return True
            for partial_count in range(1, stack_height):
                if roll % partial_count == 0:
                    effective_roll = roll // partial_count
                    if first_token.progress + effective_roll <= board_setup.squares_to_win:
                        return True

    return False
