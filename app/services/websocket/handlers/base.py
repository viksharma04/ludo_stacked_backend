"""Base types and helpers for WebSocket message handlers."""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from app.schemas.ws import (
    ErrorPayload,
    MessageType,
    RoomSnapshot,
    SeatSnapshot,
    WSClientMessage,
    WSServerMessage,
)
from app.services.room.service import RoomSnapshotData

if TYPE_CHECKING:
    from app.services.websocket.manager import ConnectionManager


@dataclass
class HandlerContext:
    """Context passed to each message handler."""

    connection_id: str
    user_id: str
    message: WSClientMessage
    manager: "ConnectionManager"


@dataclass
class HandlerResult:
    """Result returned by message handlers."""

    success: bool
    response: WSServerMessage | None = None
    broadcast: WSServerMessage | None = None
    room_id: str | None = None


def validate_request_id(request_id: str | None, error_type: MessageType) -> HandlerResult | None:
    """Validate that request_id exists and is a valid UUID.

    Args:
        request_id: The request_id to validate.
        error_type: The MessageType to use for error responses.

    Returns:
        HandlerResult with error if validation fails, None if valid.
    """
    if not request_id:
        return HandlerResult(
            success=False,
            response=WSServerMessage(
                type=error_type,
                payload=ErrorPayload(
                    error_code="VALIDATION_ERROR",
                    message="request_id is required",
                ).model_dump(),
            ),
        )

    try:
        uuid.UUID(request_id)
    except ValueError:
        return HandlerResult(
            success=False,
            response=WSServerMessage(
                type=error_type,
                request_id=request_id,
                payload=ErrorPayload(
                    error_code="VALIDATION_ERROR",
                    message="request_id must be a valid UUID",
                ).model_dump(),
            ),
        )

    return None


def validate_payload[T: BaseModel](
    payload: dict | None,
    schema: type[T],
    request_id: str | None,
    error_type: MessageType,
) -> tuple[T | None, HandlerResult | None]:
    """Validate payload against a Pydantic schema.

    Args:
        payload: The raw payload dict to validate.
        schema: The Pydantic model class to validate against.
        request_id: The request_id for error responses.
        error_type: The MessageType to use for error responses.

    Returns:
        Tuple of (validated_payload, error_result). One will be None.
    """
    try:
        validated = schema.model_validate(payload or {})
        return validated, None
    except ValidationError as e:
        return None, HandlerResult(
            success=False,
            response=WSServerMessage(
                type=error_type,
                request_id=request_id,
                payload=ErrorPayload(
                    error_code="VALIDATION_ERROR",
                    message=str(e),
                ).model_dump(),
            ),
        )


def error_response(
    error_code: str,
    message: str,
    error_type: MessageType,
    request_id: str | None = None,
) -> HandlerResult:
    """Build an error HandlerResult."""
    return HandlerResult(
        success=False,
        response=WSServerMessage(
            type=error_type,
            request_id=request_id,
            payload=ErrorPayload(
                error_code=error_code,
                message=message,
            ).model_dump(),
        ),
    )


def snapshot_to_pydantic(snapshot: RoomSnapshotData) -> RoomSnapshot:
    """Convert a dataclass RoomSnapshotData to a Pydantic RoomSnapshot."""
    return RoomSnapshot(
        room_id=snapshot.room_id,
        code=snapshot.code,
        status=snapshot.status,
        visibility=snapshot.visibility,
        ruleset_id=snapshot.ruleset_id,
        max_players=snapshot.max_players,
        seats=[
            SeatSnapshot(
                seat_index=seat.seat_index,
                user_id=seat.user_id,
                display_name=seat.display_name,
                ready=seat.ready,
                connected=seat.connected,
                is_host=seat.is_host,
            )
            for seat in snapshot.seats
        ],
        version=snapshot.version,
    )
