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

from app.schemas.game_engine import RollMoveGroup, Stack, StackState


class GameEvent(BaseModel):
    """Base class for all game events."""

    event_type: str
    seq: int = 0  # Sequence number assigned during processing


class GameStarted(GameEvent):
    """Game has transitioned from NOT_STARTED to IN_PROGRESS."""

    event_type: Literal["game_started"] = "game_started"
    player_order: list[UUID] = Field(..., description="Player IDs in turn order")
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


class StackMoved(GameEvent):
    """A stack was moved on the board."""

    event_type: Literal["stack_moved"] = "stack_moved"
    player_id: UUID
    stack_id: str
    from_state: StackState
    to_state: StackState
    from_progress: int
    to_progress: int
    roll_used: int


class StackExitedHell(GameEvent):
    """A stack moved from HELL to ROAD (got out with a 6)."""

    event_type: Literal["stack_exited_hell"] = "stack_exited_hell"
    player_id: UUID
    stack_id: str
    roll_used: int


class StackReachedHeaven(GameEvent):
    """A stack reached HEAVEN (completed its journey)."""

    event_type: Literal["stack_reached_heaven"] = "stack_reached_heaven"
    player_id: UUID
    stack_id: str


class StackCaptured(GameEvent):
    """A stack was captured and sent back to HELL."""

    event_type: Literal["stack_captured"] = "stack_captured"
    capturing_player_id: UUID
    capturing_stack_id: str = Field(..., description="ID of the capturing stack")
    captured_player_id: UUID
    captured_stack_id: str
    position: int = Field(..., description="Board position where capture occurred")
    grants_extra_roll: bool


class StackUpdate(GameEvent):
    """Describe stacks that were formed or dissolved."""

    event_type: Literal["stack_update"] = "stack_update"
    player_id: UUID
    add_stacks: list["Stack"] = Field(default_factory=list, description="New stacks formed")
    remove_stacks: list["Stack"] = Field(
        default_factory=list, description="Stacks that were dissolved"
    )


class TurnStarted(GameEvent):
    """A new turn has begun."""

    event_type: Literal["turn_started"] = "turn_started"
    player_id: UUID
    turn_number: int


class RollGranted(GameEvent):
    """Player should roll the dice.

    Emitted whenever the game expects a player to roll:
    - At the start of their turn
    - After rolling a 6 (extra roll)
    - After capturing opponent stacks (bonus roll)
    - After reaching heaven (bonus roll per piece in stack)
    """

    event_type: Literal["roll_granted"] = "roll_granted"
    player_id: UUID
    reason: Literal["turn_start", "rolled_six", "capture_bonus", "reached_heaven"]


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
    available_moves: list["RollMoveGroup"] = Field(
        ..., description="Legal moves grouped by roll value, then by parent stack"
    )


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
    final_rankings: list[UUID] = Field(..., description="Player IDs in finishing order")


# Union of all event types for type checking
AnyGameEvent = Annotated[
    GameStarted
    | DiceRolled
    | ThreeSixesPenalty
    | StackMoved
    | StackExitedHell
    | StackReachedHeaven
    | StackCaptured
    | StackUpdate
    | TurnStarted
    | RollGranted
    | TurnEnded
    | AwaitingChoice
    | AwaitingCaptureChoice
    | GameEnded,
    Field(discriminator="event_type"),
]
