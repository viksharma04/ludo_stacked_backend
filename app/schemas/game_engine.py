from enum import Enum
from uuid import UUID

from pydantic import BaseModel


# Game phases
class GamePhase(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


# Token states
class TokenState(str, Enum):
    HELL = "hell"
    ROAD = "road"
    HOMESTRETCH = "homestretch"
    HEAVEN = "heaven"


# User input events
class CurrentEvent(str, Enum):
    PLAYER_ROLL = "player_roll"
    PLAYER_CHOICE = "player_choice"
    CAPTURE_CHOICE = "capture_choice"


# Data models for game entities
# Defined pre-initialization based on db values and player setup
class PlayerAttributes(BaseModel):
    player_id: UUID
    name: str
    color: str


class GameSettings(BaseModel):
    num_players: int
    player_attributes: list[PlayerAttributes]
    grid_length: int
    get_out_rolls: list[int] = [6]


# Defined at game start
class BoardSetup(BaseModel):
    squares_to_win: int
    squares_to_homestretch: int
    starting_positions: list[int]
    safe_spaces: list[int]
    get_out_rolls: list[int]


class Token(BaseModel):
    token_id: str
    state: TokenState
    progress: int
    in_stack: bool = False


class Stack(BaseModel):
    stack_id: str
    tokens: list[str]


class Player(PlayerAttributes):
    tokens: list[Token]
    turn_order: int
    abs_starting_index: int
    stacks: list[Stack] | None = None


class Turn(BaseModel):
    player_id: UUID
    initial_roll: bool = True
    rolls_to_allocate: list[int] = []
    legal_moves: list[str] = []
    current_turn_order: int
    extra_rolls: int = 0


class Move(BaseModel):
    roll: int
    token_id: str


# Game state for broadcasting and game flow
class GameState(BaseModel):
    """Core game state - contains only actual state, no inputs.

    Actions (roll, move choice) are now handled via explicit action types
    in app.services.game.engine.actions, keeping state clean and serializable.
    """

    phase: GamePhase
    players: list[Player]
    current_event: CurrentEvent
    board_setup: BoardSetup
    current_turn: Turn | None = None
    stacks: list[Stack] | None = None
    event_seq: int = 0  # Next sequence number for events (monotonically increasing)


# Action log for recording player actions
class ActionLog(BaseModel):
    player_id: UUID
    roll: int
    token_id: str  # Or stack_id based on context
