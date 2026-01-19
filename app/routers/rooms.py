"""REST endpoints for room management."""

import logging

from fastapi import APIRouter, HTTPException, status

from app.dependencies.auth import CurrentUser
from app.schemas.room import CreateRoomRequest, CreateRoomResponse, SeatInfo
from app.services.room.service import get_room_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("", response_model=CreateRoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    current_user: CurrentUser,
    request: CreateRoomRequest,
):
    """Create a new room or return existing open room.

    If the authenticated user already owns an open room, returns that room's
    details. Otherwise, creates a new room with the user as the host in seat 0.

    Args:
        current_user: The authenticated user (from JWT).
        request: Room creation parameters (n_players: 2-4).

    Returns:
        CreateRoomResponse with room details and user's seat info.

    Raises:
        HTTPException 500: If room creation fails.
    """
    user_id = current_user.get("sub")
    logger.info(
        "POST /rooms - user: %s, n_players: %d",
        user_id,
        request.n_players,
    )

    room_service = get_room_service()
    result = await room_service.find_or_create_room(
        user_id=user_id,
        max_players=request.n_players,
        visibility="private",
        ruleset_id="classic",
        ruleset_config={},
    )

    if not result.success:
        logger.error(
            "Room creation failed for user %s: %s - %s",
            user_id,
            result.error_code,
            result.error_message,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error_message or "Failed to create room",
        )

    logger.info(
        "Room %s returned for user %s (cached=%s)",
        result.code,
        user_id,
        result.cached,
    )

    return CreateRoomResponse(
        room_id=result.room_id,
        code=result.code,
        seat=SeatInfo(
            seat_index=result.seat_index,
            is_host=result.is_host,
        ),
        cached=result.cached,
    )
