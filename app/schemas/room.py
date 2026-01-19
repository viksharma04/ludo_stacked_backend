"""Pydantic schemas for room operations."""

from pydantic import BaseModel, Field


class CreateRoomRequest(BaseModel):
    """Request body for creating a room."""

    n_players: int = Field(
        ...,
        ge=2,
        le=4,
        description="Number of players (2-4)",
    )


class SeatInfo(BaseModel):
    """Information about the user's seat in the room."""

    seat_index: int = Field(..., ge=0, le=3, description="Seat index (0-3)")
    is_host: bool = Field(..., description="Whether user is the host")


class CreateRoomResponse(BaseModel):
    """Response from room creation."""

    room_id: str = Field(..., description="UUID of the room")
    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="6-character room code",
    )
    seat: SeatInfo = Field(..., description="User's seat information")
    cached: bool = Field(
        ...,
        description="True if returning existing room, False if newly created",
    )


class JoinRoomRequest(BaseModel):
    """Request body for joining a room."""

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^[A-Z0-9]{6}$",
        description="6-character room code",
    )


class JoinRoomResponse(BaseModel):
    """Response from joining a room."""

    room_id: str = Field(..., description="UUID of the room")
    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="6-character room code",
    )
    seat: SeatInfo = Field(..., description="User's seat information")
