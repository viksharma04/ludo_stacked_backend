"""REST endpoints for room management."""

import logging

from fastapi import APIRouter, HTTPException, status

from app.dependencies.auth import CurrentUser
from app.schemas.room import (
    CreateRoomRequest,
    CreateRoomResponse,
    JoinRoomRequest,
    JoinRoomResponse,
    SeatInfo,
)
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


@router.post("/join", response_model=JoinRoomResponse, status_code=status.HTTP_200_OK)
async def join_room(
    current_user: CurrentUser,
    request: JoinRoomRequest,
):
    """Join an existing room by code.

    Validates the room code, checks availability, allocates a seat to the user,
    and returns the room details. If the user is already seated in the room,
    returns their existing seat information.

    Args:
        current_user: The authenticated user (from JWT).
        request: Join request with 6-character room code.

    Returns:
        JoinRoomResponse with room details and user's seat info.

    Raises:
        HTTPException 400: If room is closed, in game, or full.
        HTTPException 404: If room code not found.
        HTTPException 500: If join operation fails.
    """
    user_id = current_user.get("sub")
    logger.info("POST /rooms/join - user: %s, code: %s", user_id, request.code)

    room_service = get_room_service()
    result = await room_service.join_room(user_id=user_id, room_code=request.code)

    if not result.success:
        error_status_map = {
            "ROOM_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "ROOM_CLOSED": status.HTTP_400_BAD_REQUEST,
            "ROOM_IN_GAME": status.HTTP_400_BAD_REQUEST,
            "ROOM_FULL": status.HTTP_400_BAD_REQUEST,
            "INTERNAL_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }
        http_status = error_status_map.get(result.error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        logger.warning(
            "Join room failed for user %s, code %s: %s - %s",
            user_id,
            request.code,
            result.error_code,
            result.error_message,
        )
        raise HTTPException(
            status_code=http_status,
            detail=result.error_message or "Failed to join room",
        )

    # Find user's seat in the snapshot
    snapshot = result.room_snapshot
    user_seat = None
    for seat in snapshot.seats:
        if seat.user_id == user_id:
            user_seat = seat
            break

    if not user_seat:
        logger.error("User %s not found in room snapshot after successful join", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to locate seat after join",
        )

    logger.info(
        "Room %s joined by user %s (seat=%d)",
        snapshot.code,
        user_id,
        user_seat.seat_index,
    )

    return JoinRoomResponse(
        room_id=snapshot.room_id,
        code=snapshot.code,
        seat=SeatInfo(
            seat_index=user_seat.seat_index,
            is_host=user_seat.is_host,
        ),
    )
