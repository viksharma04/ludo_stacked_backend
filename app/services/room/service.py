"""Room service for managing game rooms."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from upstash_redis.asyncio import Redis

from app.dependencies.redis import get_redis_client
from app.dependencies.supabase import get_supabase_client

logger = logging.getLogger(__name__)


@dataclass
class SeatData:
    """Data for a single seat."""

    seat_index: int
    user_id: str | None = None
    display_name: str | None = None
    ready: str = "not_ready"
    connected: bool = False
    is_host: bool = False


@dataclass
class RoomSnapshotData:
    """Complete room snapshot data."""

    room_id: str
    code: str
    status: str
    visibility: str
    ruleset_id: str
    max_players: int
    seats: list[SeatData] = field(default_factory=list)
    version: int = 0


@dataclass
class JoinRoomResult:
    """Result of join_room operation."""

    success: bool
    room_snapshot: RoomSnapshotData | None = None
    error_code: str | None = None
    error_message: str | None = None


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

    def _get_user_display_name(self, user_id: str) -> str:
        """Fetch user's display_name from the profiles table.

        Returns empty string if profile not found or on error.
        """
        try:
            response = (
                self._supabase.table("profiles")
                .select("display_name")
                .eq("id", user_id)
                .single()
                .execute()
            )
            if response.data and response.data.get("display_name"):
                return response.data["display_name"]
        except Exception as e:
            logger.warning("Failed to fetch display_name for user %s: %s", user_id, e)
        return ""

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
            code = str(data.get("code", ""))
            seat_index = data.get("seat_index")
            is_host = data.get("is_host")
            cached = bool(result.get("cached", False))

            logger.info(
                "Room created: room_id=%s, code=%s, user=%s, cached=%s",
                room_id,
                code,
                user_id,
                cached,
            )

            # Initialize Redis state only for non-cached (new) rooms
            if not cached:
                # Fetch owner's display_name for the seat data
                display_name = self._get_user_display_name(user_id)

                await self._initialize_redis_state(
                    room_id=room_id,
                    owner_user_id=user_id,
                    owner_display_name=display_name,
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

    async def find_or_create_room(
        self,
        user_id: str,
        max_players: int,
        visibility: str = "private",
        ruleset_id: str = "classic",
        ruleset_config: dict[str, Any] | None = None,
    ) -> CreateRoomResult:
        """Find existing open room or create a new one.

        If the user already owns an open room, returns that room's info.
        Otherwise, creates a new room with the user as owner at seat 0.

        Args:
            user_id: The user creating/finding the room.
            max_players: Maximum number of players (2-4).
            visibility: Room visibility (currently only "private").
            ruleset_id: The ruleset to use (currently only "classic").
            ruleset_config: Optional ruleset configuration.

        Returns:
            CreateRoomResult with room details on success, or error info on failure.
        """
        if ruleset_config is None:
            ruleset_config = {}

        try:
            # Call Supabase RPC
            response = self._supabase.rpc(
                "find_or_create_room",
                {
                    "p_user_id": user_id,
                    "p_max_players": max_players,
                    "p_visibility": visibility,
                    "p_ruleset_id": ruleset_id,
                    "p_ruleset_config": ruleset_config,
                },
            ).execute()

            if not response.data:
                logger.error("Empty response from find_or_create_room RPC")
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
                    "find_or_create_room RPC failed for user %s: %s - %s",
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
            code = str(data.get("code", ""))
            seat_index = data.get("seat_index")
            is_host = data.get("is_host")
            cached = bool(result.get("cached", False))

            logger.info(
                "Room found/created: room_id=%s, code=%s, user=%s, cached=%s",
                room_id,
                code,
                user_id,
                cached,
            )

            # Initialize Redis state only for newly created rooms
            if not cached:
                display_name = self._get_user_display_name(user_id)

                await self._initialize_redis_state(
                    room_id=room_id,
                    owner_user_id=user_id,
                    owner_display_name=display_name,
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
            logger.exception("Error in find_or_create_room for user %s: %s", user_id, e)
            return CreateRoomResult(
                success=False,
                error_code="INTERNAL_ERROR",
                error_message="Failed to create room",
            )

    async def _initialize_redis_state(
        self,
        room_id: str,
        owner_user_id: str,
        owner_display_name: str,
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
                    "display_name": owner_display_name,
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

    async def get_room_snapshot(self, room_id: str) -> RoomSnapshotData | None:
        """Get a complete room snapshot from Redis.

        Returns None if the room doesn't exist in Redis.
        """
        try:
            meta_key = self._redis_room_meta_key(room_id)
            seats_key = self._redis_room_seats_key(room_id)

            # Fetch metadata and seats
            meta = await self._redis.hgetall(meta_key)
            seats_raw = await self._redis.hgetall(seats_key)

            if not meta:
                logger.warning("Room %s not found in Redis", room_id)
                return None

            # Parse seats
            seats: list[SeatData] = []
            for i in range(4):
                seat_key = f"seat:{i}"
                seat_json = seats_raw.get(seat_key, "{}")
                try:
                    seat_data = json.loads(seat_json)
                    if seat_data:
                        seats.append(
                            SeatData(
                                seat_index=i,
                                user_id=seat_data.get("user_id"),
                                display_name=seat_data.get("display_name"),
                                ready=seat_data.get("ready", "not_ready"),
                                connected=seat_data.get("connected", False),
                                is_host=seat_data.get("is_host", False),
                            )
                        )
                    else:
                        seats.append(SeatData(seat_index=i))
                except json.JSONDecodeError:
                    seats.append(SeatData(seat_index=i))

            return RoomSnapshotData(
                room_id=room_id,
                code=meta.get("code", ""),
                status=meta.get("status", "unknown"),
                visibility=meta.get("visibility", "private"),
                ruleset_id=meta.get("ruleset_id", "classic"),
                max_players=int(meta.get("max_players", 4)),
                seats=seats,
                version=int(meta.get("version", 0)),
            )

        except Exception as e:
            logger.exception("Error getting room snapshot for %s: %s", room_id, e)
            return None

    def _resolve_room_code(self, code: str, user_id: str) -> tuple[str | None, str | None]:
        """Resolve a room code to room_id with authorization.

        Returns: (room_id, error_code) - one will be None.

        Error codes:
        - ROOM_NOT_FOUND: Code doesn't exist
        - ROOM_CLOSED: Room is closed
        - ROOM_IN_GAME: Room in game and user is not a member
        """
        try:
            response = (
                self._supabase.table("rooms")
                .select("room_id, status")
                .eq("code", code.upper())
                .single()
                .execute()
            )

            if not response.data:
                return None, "ROOM_NOT_FOUND"

            room_id = str(response.data["room_id"])
            status = str(response.data["status"])

            if status == "closed":
                return None, "ROOM_CLOSED"

            if status == "in_game":
                # Check if user is already a member (has a seat)
                if not self._is_user_room_member(room_id, user_id):
                    return None, "ROOM_IN_GAME"

            return room_id, None

        except Exception as e:
            logger.warning("Error resolving room code %s: %s", code, e)
            return None, "ROOM_NOT_FOUND"

    def _is_user_room_member(self, room_id: str, user_id: str) -> bool:
        """Check if a user is a member (seated) in a room."""
        try:
            response = (
                self._supabase.table("room_seats")
                .select("id")
                .eq("room_id", room_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            logger.warning("Error checking room membership for user %s: %s", user_id, e)
            return False

    async def join_room(self, user_id: str, room_code: str) -> JoinRoomResult:
        """Join a room and allocate a seat.

        This resolves the room code to a room_id with authorization checks,
        allocates a seat for the user (if not already seated),
        updates both DB and Redis, and returns an authoritative room snapshot.

        Args:
            user_id: The user joining the room.
            room_code: The 6-character room code to join.

        Returns:
            JoinRoomResult with room snapshot on success, or error info on failure.
        """
        try:
            # Resolve room code to room_id with authorization
            room_id, error_code = self._resolve_room_code(room_code, user_id)
            if error_code:
                error_messages = {
                    "ROOM_NOT_FOUND": "Room not found",
                    "ROOM_CLOSED": "Room is closed",
                    "ROOM_IN_GAME": "Room is in game",
                }
                return JoinRoomResult(
                    success=False,
                    error_code=error_code,
                    error_message=error_messages.get(error_code, "Unknown error"),
                )

            # Get room snapshot from Redis
            snapshot = await self.get_room_snapshot(room_id)
            if not snapshot:
                logger.warning("Room %s not found in Redis for join", room_id)
                return JoinRoomResult(
                    success=False,
                    error_code="ROOM_NOT_FOUND",
                    error_message="Room not found",
                )

            # Check if user is already seated (idempotent rejoin)
            existing_seat = None
            for seat in snapshot.seats:
                if seat.user_id == user_id:
                    existing_seat = seat
                    break

            if existing_seat:
                # User already seated, just update connected status and return snapshot
                await self._update_seat_connected(room_id, existing_seat.seat_index, True)
                snapshot = await self.get_room_snapshot(room_id)
                logger.info(
                    "User %s rejoined room %s at seat %d",
                    user_id,
                    room_id,
                    existing_seat.seat_index,
                )
                return JoinRoomResult(
                    success=True,
                    room_snapshot=snapshot,
                )

            # Find first empty seat
            empty_seat_index = None
            for seat in snapshot.seats:
                if seat.user_id is None:
                    empty_seat_index = seat.seat_index
                    break

            if empty_seat_index is None:
                return JoinRoomResult(
                    success=False,
                    error_code="ROOM_FULL",
                    error_message="Room is full",
                )

            # Get user's display name
            display_name = self._get_user_display_name(user_id)

            # Update DB first
            db_updated = self._update_seat_in_db(room_id, empty_seat_index, user_id)
            if not db_updated:
                return JoinRoomResult(
                    success=False,
                    error_code="INTERNAL_ERROR",
                    error_message="Failed to allocate seat",
                )

            # Update Redis
            await self._update_seat_in_redis(
                room_id=room_id,
                seat_index=empty_seat_index,
                user_id=user_id,
                display_name=display_name,
                is_host=False,
                connected=True,
            )

            # Register presence
            presence_key = f"room:{room_id}:presence"
            await self._redis.sadd(presence_key, user_id)
            await self._redis.expire(presence_key, 300)

            # Fetch updated snapshot
            snapshot = await self.get_room_snapshot(room_id)

            logger.info("User %s joined room %s at seat %d", user_id, room_id, empty_seat_index)

            return JoinRoomResult(
                success=True,
                room_snapshot=snapshot,
            )

        except Exception as e:
            logger.exception(
                "Error joining room with code %s for user %s: %s", room_code, user_id, e
            )
            return JoinRoomResult(
                success=False,
                error_code="INTERNAL_ERROR",
                error_message="Failed to join room",
            )

    def _update_seat_in_db(self, room_id: str, seat_index: int, user_id: str) -> bool:
        """Update a seat in the database."""
        try:
            response = (
                self._supabase.table("room_seats")
                .update({"user_id": user_id})
                .eq("room_id", room_id)
                .eq("seat_index", seat_index)
                .is_("user_id", "null")  # Only update if seat is empty (optimistic lock)
                .execute()
            )
            # Check if a row was actually updated
            if response.data and len(response.data) > 0:
                return True
            logger.warning(
                "Seat %d in room %s was not updated (possibly taken)", seat_index, room_id
            )
            return False
        except Exception as e:
            logger.exception("Error updating seat in DB: %s", e)
            return False

    async def _update_seat_in_redis(
        self,
        room_id: str,
        seat_index: int,
        user_id: str,
        display_name: str,
        is_host: bool,
        connected: bool,
    ) -> None:
        """Update a seat in Redis."""
        seats_key = self._redis_room_seats_key(room_id)
        now_ms = int(time.time() * 1000)
        seat_data = json.dumps(
            {
                "user_id": user_id,
                "display_name": display_name,
                "ready": "not_ready",
                "connected": connected,
                "is_host": is_host,
                "joined_at_ms": now_ms,
            }
        )
        await self._redis.hset(seats_key, f"seat:{seat_index}", seat_data)

    async def _update_seat_connected(self, room_id: str, seat_index: int, connected: bool) -> None:
        """Update the connected status of a seat in Redis."""
        seats_key = self._redis_room_seats_key(room_id)
        seat_json = await self._redis.hget(seats_key, f"seat:{seat_index}")
        if seat_json:
            try:
                seat_data = json.loads(seat_json)
                seat_data["connected"] = connected
                await self._redis.hset(seats_key, f"seat:{seat_index}", json.dumps(seat_data))
            except json.JSONDecodeError:
                pass

    async def remove_presence(self, user_id: str, room_id: str) -> None:
        """Remove user presence from a room."""
        try:
            presence_key = f"room:{room_id}:presence"
            await self._redis.srem(presence_key, user_id)
            logger.debug("Removed presence for user %s from room %s", user_id, room_id)
        except Exception as e:
            logger.warning(
                "Failed to remove presence for user %s from room %s: %s",
                user_id,
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
