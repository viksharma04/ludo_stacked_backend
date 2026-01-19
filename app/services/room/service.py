"""Room service for managing game rooms."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from upstash_redis.asyncio import Redis

from app.dependencies.redis import get_redis_client
from app.dependencies.supabase import get_supabase_client

logger = logging.getLogger(__name__)


@dataclass
class CreateRoomResult:
    """Result of create_room operation."""

    success: bool
    room_id: str | None = None
    code: str | None = None
    seat_index: int | None = None
    is_host: bool | None = None
    cached: bool = False
    error_code: str | None = None
    error_message: str | None = None


class RoomService:
    """Service for managing game rooms.

    Handles room creation via Supabase RPC and Redis state initialization.
    """

    def __init__(self, redis_client: Redis | None = None):
        self._redis = redis_client or get_redis_client()
        self._supabase = get_supabase_client()

    def _redis_room_meta_key(self, room_id: str) -> str:
        return f"room:{room_id}:meta"

    def _redis_room_seats_key(self, room_id: str) -> str:
        return f"room:{room_id}:seats"

    async def create_room(
        self,
        user_id: str,
        request_id: str,
        visibility: str,
        max_players: int,
        ruleset_id: str,
        ruleset_config: dict[str, Any],
    ) -> CreateRoomResult:
        """Create a new game room.

        Calls the Supabase RPC function which handles:
        - Idempotency checking
        - Room code generation with collision retry
        - Room and seat creation in a single transaction

        If the RPC succeeds and returns a non-cached result, initializes Redis state.

        Args:
            user_id: The user creating the room.
            request_id: Unique request ID for idempotency.
            visibility: Room visibility (currently only "private").
            max_players: Maximum number of players (2-4).
            ruleset_id: The ruleset to use (currently only "classic").
            ruleset_config: Optional ruleset configuration.

        Returns:
            CreateRoomResult with room details on success, or error info on failure.
        """
        try:
            # Call Supabase RPC
            response = self._supabase.rpc(
                "create_room",
                {
                    "p_user_id": user_id,
                    "p_request_id": request_id,
                    "p_visibility": visibility,
                    "p_max_players": max_players,
                    "p_ruleset_id": ruleset_id,
                    "p_ruleset_config": ruleset_config,
                },
            ).execute()

            if not response.data:
                logger.error("Empty response from create_room RPC")
                return CreateRoomResult(
                    success=False,
                    error_code="INTERNAL_ERROR",
                    error_message="Empty response from database",
                )

            result = response.data

            # Check if RPC returned an error
            if not result.get("success"):
                error_code = result.get("error", "INTERNAL_ERROR")
                error_message = result.get("message", "Unknown error")
                logger.warning(
                    "create_room RPC failed for user %s: %s - %s",
                    user_id,
                    error_code,
                    error_message,
                )
                return CreateRoomResult(
                    success=False,
                    error_code=error_code,
                    error_message=error_message,
                )

            # Extract room data
            data = result.get("data", {})
            room_id = str(data.get("room_id"))
            code = data.get("code")
            seat_index = data.get("seat_index")
            is_host = data.get("is_host")
            cached = result.get("cached", False)

            logger.info(
                "Room created: room_id=%s, code=%s, user=%s, cached=%s",
                room_id,
                code,
                user_id,
                cached,
            )

            # Initialize Redis state only for non-cached (new) rooms
            if not cached:
                await self._initialize_redis_state(
                    room_id=room_id,
                    owner_user_id=user_id,
                    code=code,
                    visibility=visibility,
                    max_players=max_players,
                    ruleset_id=ruleset_id,
                    ruleset_config=ruleset_config,
                )

            return CreateRoomResult(
                success=True,
                room_id=room_id,
                code=code,
                seat_index=seat_index,
                is_host=is_host,
                cached=cached,
            )

        except Exception as e:
            logger.exception("Error creating room for user %s: %s", user_id, e)
            return CreateRoomResult(
                success=False,
                error_code="INTERNAL_ERROR",
                error_message="Failed to create room",
            )

    async def _initialize_redis_state(
        self,
        room_id: str,
        owner_user_id: str,
        code: str,
        visibility: str,
        max_players: int,
        ruleset_id: str,
        ruleset_config: dict[str, Any],
    ) -> None:
        """Initialize Redis state for a newly created room.

        Sets up:
        - room:{room_id}:meta hash with room metadata
        - room:{room_id}:seats hash with seat information

        This is best-effort - failures are logged but don't rollback the room creation.
        """
        now_ms = int(time.time() * 1000)

        try:
            # Initialize room metadata
            meta_key = self._redis_room_meta_key(room_id)
            await self._redis.hset(
                meta_key,
                values={
                    "status": "open",
                    "visibility": visibility,
                    "owner_user_id": owner_user_id,
                    "code": code,
                    "max_players": str(max_players),
                    "ruleset_id": ruleset_id,
                    "ruleset_config": json.dumps(ruleset_config),
                    "created_at_ms": str(now_ms),
                    "version": "0",
                },
            )

            # Initialize room seats
            seats_key = self._redis_room_seats_key(room_id)
            seat_data = {}

            # Seat 0 is occupied by the owner
            seat_data["seat:0"] = json.dumps(
                {
                    "user_id": owner_user_id,
                    "display_name": "",
                    "ready": "not_ready",
                    "connected": True,
                    "is_host": True,
                    "joined_at_ms": now_ms,
                }
            )

            # Seats 1-3 are empty
            for i in range(1, 4):
                seat_data[f"seat:{i}"] = json.dumps({})

            await self._redis.hset(seats_key, values=seat_data)

            logger.debug("Redis state initialized for room %s", room_id)

        except Exception as e:
            logger.error(
                "Failed to initialize Redis state for room %s: %s",
                room_id,
                e,
            )


# Singleton instance
_room_service: RoomService | None = None


def get_room_service() -> RoomService:
    """Get the singleton RoomService instance."""
    global _room_service
    if _room_service is None:
        _room_service = RoomService()
    return _room_service
