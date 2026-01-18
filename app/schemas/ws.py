from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """WebSocket message types."""

    PING = "ping"
    PONG = "pong"
    CONNECTED = "connected"
    ERROR = "error"


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


class WSClientMessage(BaseModel):
    """Message sent from client to server."""

    type: MessageType
    timestamp: datetime | None = None
    request_id: str | None = None
    payload: dict[str, Any] | None = None


class WSServerMessage(BaseModel):
    """Message sent from server to client."""

    type: MessageType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: str | None = None
    payload: dict[str, Any] | None = None
    error: str | None = None
    code: int | None = None


class ConnectedPayload(BaseModel):
    """Payload for the 'connected' message."""

    connection_id: str
    user_id: str
    server_id: str


class PongPayload(BaseModel):
    """Payload for the 'pong' message."""

    server_time: datetime = Field(default_factory=datetime.utcnow)
