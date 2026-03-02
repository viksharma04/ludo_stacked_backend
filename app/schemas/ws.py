from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """WebSocket message types."""

    # Authentication
    AUTHENTICATE = "authenticate"
    AUTHENTICATED = "authenticated"

    # Core
    PING = "ping"
    PONG = "pong"
    ERROR = "error"
    ROOM_UPDATED = "room_updated"
    TOGGLE_READY = "toggle_ready"
    LEAVE_ROOM = "leave_room"
    ROOM_CLOSED = "room_closed"

    # Game
    START_GAME = "start_game"
    GAME_STARTED = "game_started"
    GAME_ACTION = "game_action"
    GAME_EVENTS = "game_events"
    GAME_STATE = "game_state"
    GAME_ERROR = "game_error"


class WSCloseCode:
    """WebSocket close codes (RFC 6455 + custom)."""

    # Standard RFC 6455 codes
    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    INVALID_DATA = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    INTERNAL_ERROR = 1011

    # Custom application codes (4000-4999)
    AUTH_FAILED = 4001
    AUTH_EXPIRED = 4002
    ROOM_NOT_FOUND = 4003
    ROOM_ACCESS_DENIED = 4004
    AUTH_TIMEOUT = 4005


class WSClientMessage(BaseModel):
    """Message sent from client to server."""

    type: MessageType
    request_id: str | None = None
    payload: dict[str, Any] | None = None


class WSServerMessage(BaseModel):
    """Message sent from server to client."""

    type: MessageType
    request_id: str | None = None
    payload: dict[str, Any] | None = None


# --- Payload schemas ---


class SeatSnapshot(BaseModel):
    """Snapshot of a single seat in a room."""

    seat_index: int
    user_id: str | None = None
    display_name: str | None = None
    ready: str = "not_ready"
    connected: bool = False
    is_host: bool = False


class RoomSnapshot(BaseModel):
    """Authoritative room snapshot for lobby rendering.

    Used as payload for ROOM_UPDATED and AUTHENTICATED messages.
    """

    room_id: str
    code: str
    status: str
    visibility: str
    ruleset_id: str
    max_players: int
    seats: list[SeatSnapshot]
    version: int = 0


class PongPayload(BaseModel):
    """Payload for the 'pong' message."""

    server_time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ErrorPayload(BaseModel):
    """Payload for error messages."""

    error_code: str
    message: str


class RoomClosedPayload(BaseModel):
    """Payload sent when host closes the room."""

    reason: str = "host_left"
    room_id: str


class AuthenticatePayload(BaseModel):
    """Payload for the 'authenticate' message from client."""

    token: str = Field(..., min_length=1)
    room_code: str = Field(..., min_length=6, max_length=6, pattern="^[A-Z0-9]{6}$")


class AuthenticatedPayload(BaseModel):
    """Payload for the 'authenticated' message sent to client on successful auth."""

    connection_id: str
    user_id: str
    server_id: str
    room: RoomSnapshot


# --- Game payload schemas ---


class GameActionPayload(BaseModel):
    """Payload for GAME_ACTION messages from client.

    Contains the action type and action-specific data.
    """

    action_type: str = Field(
        ..., description="Action type: 'roll', 'move', 'capture_choice', 'start_game'"
    )
    value: int | None = Field(None, ge=1, le=6, description="Dice value for roll action")
    stack_id: str | None = Field(None, description="Stack ID for move action")
    roll_value: int | None = Field(
        None, ge=1, le=6, description="Which roll value to consume for move action"
    )
    choice: str | None = Field(None, description="Choice for capture_choice action")


class GameEventsPayload(BaseModel):
    """Payload for GAME_EVENTS messages to clients.

    Contains a list of events that occurred during action processing.
    Events are broadcast to all room members for animation/UI updates.
    """

    events: list[dict[str, Any]] = Field(
        ..., description="List of game events (serialized)"
    )


class GameStartedPayload(BaseModel):
    """Payload for GAME_STARTED message broadcast to all players.

    Contains the initial game state and startup events.
    """

    game_state: dict[str, Any] = Field(..., description="Full game state (serialized)")
    events: list[dict[str, Any]] = Field(
        ..., description="List of game events (game_started, turn_started)"
    )
