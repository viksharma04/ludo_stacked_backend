"""Game event types - emitted during state transitions for WebSocket broadcasts.

Events describe what happened during a game action, enabling:
- Efficient WebSocket updates (only send what changed)
- Frontend animations (know exactly what transitioned)
- Action replay / audit logging
- Reconnection state catch-up
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.game_engine import TokenState


class GameEvent(BaseModel):
    """Base class for all game events."""

    event_type: str
    seq: int = 0  # Sequence number assigned during processing


class GameStarted(GameEvent):
    """Game has transitioned from NOT_STARTED to IN_PROGRESS."""

    event_type: Literal["game_started"] = "game_started"
    player_order: list[UUID] = Field(
        ..., description="Player IDs in turn order"
    )
    first_player_id: UUID


class DiceRolled(GameEvent):
    """A player rolled the dice."""

    event_type: Literal["dice_rolled"] = "dice_rolled"
    player_id: UUID
    value: int = Field(..., ge=1, le=6)
    roll_number: int = Field(..., description="Which roll in this turn (1, 2, 3...)")
    grants_extra_roll: bool = Field(
        ..., description="True if this roll grants another roll (rolled a 6)"
    )


class ThreeSixesPenalty(GameEvent):
    """Player rolled three consecutive sixes and loses their turn."""

    event_type: Literal["three_sixes_penalty"] = "three_sixes_penalty"
    player_id: UUID
    rolls: list[int] = Field(..., description="The three six values")


class TokenMoved(GameEvent):
    """A token was moved on the board."""

    event_type: Literal["token_moved"] = "token_moved"
    player_id: UUID
    token_id: str
    from_state: TokenState
    to_state: TokenState
    from_progress: int
    to_progress: int
    roll_used: int


class TokenExitedHell(GameEvent):
    """A token moved from HELL to ROAD (got out with a 6)."""

    event_type: Literal["token_exited_hell"] = "token_exited_hell"
    player_id: UUID
    token_id: str
    roll_used: int


class TokenReachedHeaven(GameEvent):
    """A token reached HEAVEN (completed its journey)."""

    event_type: Literal["token_reached_heaven"] = "token_reached_heaven"
    player_id: UUID
    token_id: str


class TokenCaptured(GameEvent):
    """A token was captured and sent back to HELL."""

    event_type: Literal["token_captured"] = "token_captured"
    capturing_player_id: UUID
    capturing_token_id: str
    captured_player_id: UUID
    captured_token_id: str
    position: int = Field(..., description="Board position where capture occurred")
    grants_extra_roll: bool


class StackFormed(GameEvent):
    """Multiple tokens of the same player stacked together."""

    event_type: Literal["stack_formed"] = "stack_formed"
    player_id: UUID
    stack_id: str
    token_ids: list[str]
    position: int


class StackDissolved(GameEvent):
    """A stack was broken apart (e.g., captured or split)."""

    event_type: Literal["stack_dissolved"] = "stack_dissolved"
    player_id: UUID
    stack_id: str
    token_ids: list[str]
    reason: str = Field(..., description="Why the stack dissolved: 'captured', 'split'")


class StackSplit(GameEvent):
    """A stack was split into two groups (partial stack move)."""

    event_type: Literal["stack_split"] = "stack_split"
    player_id: UUID
    original_stack_id: str
    moving_token_ids: list[str] = Field(
        ..., description="Token IDs being moved from the stack"
    )
    remaining_token_ids: list[str] = Field(
        ..., description="Token IDs remaining in the original position"
    )
    new_stack_id: str | None = Field(
        None, description="New stack ID for moving tokens, or None if they become individual"
    )


class StackMoved(GameEvent):
    """A stack was moved on the board."""

    event_type: Literal["stack_moved"] = "stack_moved"
    player_id: UUID
    stack_id: str
    token_ids: list[str]
    from_progress: int
    to_progress: int
    roll_used: int
    effective_roll: int = Field(
        ..., description="Actual movement = roll / stack_height"
    )


class TurnStarted(GameEvent):
    """A new turn has begun."""

    event_type: Literal["turn_started"] = "turn_started"
    player_id: UUID
    turn_number: int


class TurnEnded(GameEvent):
    """A player's turn has ended."""

    event_type: Literal["turn_ended"] = "turn_ended"
    player_id: UUID
    reason: str = Field(
        ...,
        description="Why turn ended: 'no_legal_moves', 'all_rolls_used', 'three_sixes'",
    )
    next_player_id: UUID


class AwaitingChoice(GameEvent):
    """Game is waiting for player to choose a move."""

    event_type: Literal["awaiting_choice"] = "awaiting_choice"
    player_id: UUID
    legal_moves: list[str] = Field(
        ..., description="Token/stack IDs that can be moved"
    )
    roll_to_allocate: int


class AwaitingCaptureChoice(GameEvent):
    """Game is waiting for player to resolve a capture situation."""

    event_type: Literal["awaiting_capture_choice"] = "awaiting_capture_choice"
    player_id: UUID
    options: list[str] = Field(
        ..., description="Available choices: 'stack', 'capture', or target IDs"
    )


class GameEnded(GameEvent):
    """The game has finished."""

    event_type: Literal["game_ended"] = "game_ended"
    winner_id: UUID
    final_rankings: list[UUID] = Field(
        ..., description="Player IDs in finishing order"
    )


# Union of all event types for type checking
AnyGameEvent = Annotated[
    GameStarted
    | DiceRolled
    | ThreeSixesPenalty
    | TokenMoved
    | TokenExitedHell
    | TokenReachedHeaven
    | TokenCaptured
    | StackFormed
    | StackDissolved
    | StackSplit
    | StackMoved
    | TurnStarted
    | TurnEnded
    | AwaitingChoice
    | AwaitingCaptureChoice
    | GameEnded,
    Field(discriminator="event_type"),
]
