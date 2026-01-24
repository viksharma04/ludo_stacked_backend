"""Capture detection and resolution logic."""

from dataclasses import dataclass, field
from uuid import UUID

from app.schemas.game_engine import (
    BoardSetup,
    GameState,
    Player,
    Stack,
    Token,
    TokenState,
)

from .events import (
    AnyGameEvent,
    StackDissolved,
    StackFormed,
    TokenCaptured,
)


@dataclass
class CollisionResult:
    """Result of resolving a collision."""

    state: GameState | None = None
    events: list[AnyGameEvent] = field(default_factory=list)
    requires_choice: bool = False


def get_absolute_position(
    piece: Token | Stack,
    player: Player,
    board_setup: BoardSetup,
) -> int:
    """Calculate the absolute board position of a token or stack.

    Args:
        piece: Token or Stack to get position for.
        player: The player who owns the piece.
        board_setup: Board configuration.

    Returns:
        Absolute position on the shared road (0 to squares_to_homestretch-1).
    """
    if isinstance(piece, Token):
        progress = piece.progress
    else:
        # For stacks, get position from first token
        first_token_id = piece.tokens[0]
        first_token = next(t for t in player.tokens if t.token_id == first_token_id)
        progress = first_token.progress

    return (player.abs_starting_index + progress) % board_setup.squares_to_homestretch


def detect_collisions(
    state: GameState,
    moved_piece: Token | Stack,
    moving_player: Player,
    board_setup: BoardSetup,
) -> list[tuple[Player, Token | Stack]]:
    """Detect all pieces at the same position as the moved piece.

    Only checks pieces on ROAD (not HELL, HOMESTRETCH, or HEAVEN).

    Args:
        state: Current game state.
        moved_piece: The token or stack that just moved.
        moving_player: The player who moved.
        board_setup: Board configuration.

    Returns:
        List of (player, piece) tuples for all colliding pieces.
    """
    moved_position = get_absolute_position(moved_piece, moving_player, board_setup)
    collisions: list[tuple[Player, Token | Stack]] = []

    # Get the moved piece's ID for comparison
    moved_id = moved_piece.token_id if isinstance(moved_piece, Token) else moved_piece.stack_id

    for player in state.players:
        # Check individual tokens (not in stacks)
        for token in player.tokens:
            # Skip the moved piece itself
            if isinstance(moved_piece, Token) and token.token_id == moved_id:
                continue

            # Skip tokens in stacks (they're handled with their stack)
            if token.in_stack:
                continue

            # Only check ROAD tokens
            if token.state != TokenState.ROAD:
                continue

            token_pos = get_absolute_position(token, player, board_setup)
            if token_pos == moved_position:
                collisions.append((player, token))

        # Check stacks
        if player.stacks:
            for stack in player.stacks:
                # Skip the moved stack itself
                if isinstance(moved_piece, Stack) and stack.stack_id == moved_id:
                    continue

                # Get stack position from first token
                first_token_id = stack.tokens[0]
                first_token = next((t for t in player.tokens if t.token_id == first_token_id), None)
                if first_token is None or first_token.state != TokenState.ROAD:
                    continue

                stack_pos = get_absolute_position(stack, player, board_setup)
                if stack_pos == moved_position:
                    collisions.append((player, stack))

    return collisions


def resolve_collision(
    state: GameState,
    capturing_player: Player,
    capturing_piece: Token | Stack,
    other_player: Player,
    other_piece: Token | Stack,
    events: list[AnyGameEvent],
) -> CollisionResult:
    """Resolve a collision between two pieces.

    Collision rules:
    - Same player: Form a stack (or merge stacks)
    - Different player, single tokens: Capture (send to HELL)
    - Different player with stacks: Complex capture rules

    Args:
        state: Current game state.
        capturing_player: Player who just moved.
        capturing_piece: The piece that moved.
        other_player: Player who owns the other piece.
        other_piece: The stationary piece.
        events: Events list to append to.

    Returns:
        CollisionResult with updated state and events.
    """
    same_player = capturing_player.player_id == other_player.player_id

    if same_player:
        return resolve_stacking(state, capturing_player, capturing_piece, other_piece)
    else:
        # If the current position is a safe space, no capture occurs
        # Check if the position is a safe space

        moved_position = get_absolute_position(capturing_piece, capturing_player, state.board_setup)
        if moved_position in state.board_setup.safe_spaces:
            return CollisionResult(state=state, events=events)

        return resolve_capture(
            state, capturing_player, capturing_piece, other_player, other_piece, events
        )


def resolve_stacking(
    state: GameState,
    player: Player,
    piece1: Token | Stack,
    piece2: Token | Stack,
) -> CollisionResult:
    """Resolve a stacking situation (same player's pieces meet).

    Args:
        state: Current game state.
        player: The player whose pieces are stacking.
        piece1: First piece (the one that moved).
        piece2: Second piece (the stationary one).

    Returns:
        CollisionResult with updated state and stack events.
    """
    events: list[AnyGameEvent] = []

    # Collect all token IDs involved
    token_ids: list[str] = []

    if isinstance(piece1, Token):
        token_ids.append(piece1.token_id)
    else:
        token_ids.extend(piece1.tokens)

    if isinstance(piece2, Token):
        token_ids.append(piece2.token_id)
    else:
        token_ids.extend(piece2.tokens)

    # Create new stack ID
    stack_id = f"{player.player_id}_stack_{len(player.stacks or []) + 1}"

    # Update tokens to be in_stack
    updated_tokens = []
    for token in player.tokens:
        if token.token_id in token_ids:
            updated_tokens.append(token.model_copy(update={"in_stack": True}))
        else:
            updated_tokens.append(token)

    # Remove old stacks that are being merged
    old_stacks = player.stacks or []
    remaining_stacks = [
        s
        for s in old_stacks
        if not (
            (isinstance(piece1, Stack) and s.stack_id == piece1.stack_id)
            or (isinstance(piece2, Stack) and s.stack_id == piece2.stack_id)
        )
    ]

    # Add new stack
    new_stack = Stack(stack_id=stack_id, tokens=token_ids)
    updated_stacks = [*remaining_stacks, new_stack]

    # Get position for the event
    first_token = next(t for t in player.tokens if t.token_id == token_ids[0])
    position = first_token.progress

    events.append(
        StackFormed(
            player_id=player.player_id,
            stack_id=stack_id,
            token_ids=token_ids,
            position=position,
        )
    )

    updated_player = player.model_copy(update={"tokens": updated_tokens, "stacks": updated_stacks})
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]
    updated_state = state.model_copy(update={"players": updated_players})

    return CollisionResult(state=updated_state, events=events)


def resolve_capture(
    state: GameState,
    capturing_player: Player,
    capturing_piece: Token | Stack,
    captured_player: Player,
    captured_piece: Token | Stack,
    _events: list[AnyGameEvent],  # Not used; function returns its own events
) -> CollisionResult:
    """Resolve a capture (different players' pieces meet).

    Rules:
    - Moving piece equal or larger than stationary piece: Stationary piece captured (sent to HELL)
    - Moving piece smaller than stationary piece: No capture occurs (stationary piece is safe)
    - Capturing grants an extra roll

    Args:
        state: Current game state.
        capturing_player: Player who moved.
        capturing_piece: The moving piece.
        captured_player: Player being captured.
        captured_piece: The stationary piece.
        events: Events list to append to.

    Returns:
        CollisionResult with updated state and capture events.
    """
    new_events: list[AnyGameEvent] = []

    # Determine sizes
    if isinstance(capturing_piece, Token):
        capturing_size = 1
        capturing_token_ids = [capturing_piece.token_id]
    else:
        capturing_size = len(capturing_piece.tokens)
        capturing_token_ids = capturing_piece.tokens

    if isinstance(captured_piece, Token):
        captured_size = 1
        captured_token_ids = [captured_piece.token_id]
    else:
        captured_size = len(captured_piece.tokens)
        captured_token_ids = captured_piece.tokens

    # Get position for events
    if isinstance(capturing_piece, Token):
        position = capturing_piece.progress
    else:
        first_token = next(
            t for t in capturing_player.tokens if t.token_id == capturing_piece.tokens[0]
        )
        position = first_token.progress

    updated_state = state

    if capturing_size >= captured_size:
        # Capturing piece wins - captured piece goes to HELL
        updated_state = send_to_hell(updated_state, captured_player, captured_token_ids)

        # Dissolve captured stack if applicable
        if isinstance(captured_piece, Stack):
            new_events.append(
                StackDissolved(
                    player_id=captured_player.player_id,
                    stack_id=captured_piece.stack_id,
                    token_ids=captured_token_ids,
                    reason="captured",
                )
            )

        for token_id in captured_token_ids:
            new_events.append(
                TokenCaptured(
                    capturing_player_id=capturing_player.player_id,
                    capturing_token_id=capturing_token_ids[0],
                    captured_player_id=captured_player.player_id,
                    captured_token_id=token_id,
                    position=position,
                    grants_extra_roll=True,
                )
            )

        # Grant extra roll
        updated_state = grant_extra_roll(updated_state)

    elif captured_size > capturing_size:
        # Captured piece is safe - no capture occurs
        pass

    return CollisionResult(state=updated_state, events=new_events)


def send_to_hell(
    state: GameState,
    player: Player,
    token_ids: list[str],
) -> GameState:
    """Send specified tokens back to HELL.

    Args:
        state: Current game state.
        player: Player whose tokens are being sent to HELL.
        token_ids: List of token IDs to send to HELL.

    Returns:
        Updated game state.
    """
    # Get fresh player from state
    current_player = next(p for p in state.players if p.player_id == player.player_id)

    updated_tokens = []
    for token in current_player.tokens:
        if token.token_id in token_ids:
            updated_tokens.append(
                token.model_copy(
                    update={
                        "state": TokenState.HELL,
                        "progress": 0,
                        "in_stack": False,
                    }
                )
            )
        else:
            updated_tokens.append(token)

    # Remove any stacks containing these tokens
    updated_stacks = None
    if current_player.stacks:
        updated_stacks = [
            s for s in current_player.stacks if not any(tid in token_ids for tid in s.tokens)
        ]
        if not updated_stacks:
            updated_stacks = None

    updated_player = current_player.model_copy(
        update={"tokens": updated_tokens, "stacks": updated_stacks}
    )
    updated_players = [
        updated_player if p.player_id == player.player_id else p for p in state.players
    ]

    return state.model_copy(update={"players": updated_players})


def grant_extra_roll(state: GameState) -> GameState:
    """Grant an extra roll to the current player.

    Args:
        state: Current game state.

    Returns:
        Updated game state with extra_rolls incremented.
    """
    if state.current_turn is None:
        return state

    updated_turn = state.current_turn.model_copy(
        update={"extra_rolls": state.current_turn.extra_rolls + 1}
    )
    return state.model_copy(update={"current_turn": updated_turn})


def process_capture_choice(
    state: GameState,
    _choice: str,
    _player_id: UUID,
) -> CollisionResult:
    """Process a capture choice made by the player.

    Used when there are multiple capture options (e.g., multiple targets).

    Args:
        state: Current game state.
        _choice: The player's choice ('stack', 'capture', or target ID).
        _player_id: The player making the choice.

    Returns:
        CollisionResult with updated state.
    """
    # Placeholder for complex capture choice logic
    # This would be used when a player has multiple options
    return CollisionResult(state=state, events=[])
