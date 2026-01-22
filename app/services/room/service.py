"""Room service for managing game rooms."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from supabase import AsyncClient
from upstash_redis.asyncio import Redis

from app.dependencies.redis import get_redis_client
from app.dependencies.supabase import get_async_supabase

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


@dataclass
class ToggleReadyResult:
    """Result of toggle_ready operation."""

    success: bool
    new_ready_state: str | None = None
    room_status_changed: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class LeaveRoomResult:
    """Result of leave_room operation."""

    success: bool
    was_host: bool = False
    room_closed: bool = False
    room_snapshot: RoomSnapshotData | None = None
    error_code: str | None = None
    error_message: str | None = None


class RoomService:
    """Service for managing game rooms.

    Handles room creation via Supabase RPC and Redis state initialization.
    Uses async Supabase client to avoid blocking the event loop.
    """

    def __init__(
        self, redis_client: Redis | None = None, supabase_client: AsyncClient | None = None
    ):
        self._redis = redis_client or get_redis_client()
        self._supabase = supabase_client or get_async_supabase()

    def _redis_room_meta_key(self, room_id: str) -> str:
        return f"room:{room_id}:meta"

    def _redis_room_seats_key(self, room_id: str) -> str:
        return f"room:{room_id}:seats"

    async def _get_user_display_name(self, user_id: str) -> str:
        """Fetch user's display_name from the profiles table.

        Returns empty string if profile not found or on error.
        """
        try:
            response = await (
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
            response = await self._supabase.rpc(
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
                display_name = await self._get_user_display_name(user_id)

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
            response = await self._supabase.rpc(
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
                display_name = await self._get_user_display_name(user_id)

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

            # Remaining seats are empty (seats 1 through max_players-1)
            for i in range(1, max_players):
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

            # Parse max_players for seat count
            max_players = int(meta.get("max_players", 4))

            # Parse seats
            seats: list[SeatData] = []
            for i in range(max_players):
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
                max_players=max_players,
                seats=seats,
                version=int(meta.get("version", 0)),
            )

        except Exception as e:
            logger.exception("Error getting room snapshot for %s: %s", room_id, e)
            return None

    async def _resolve_room_code(self, code: str, user_id: str) -> tuple[str | None, str | None]:
        """Resolve a room code to room_id with authorization.

        Returns: (room_id, error_code) - one will be None.

        Error codes:
        - ROOM_NOT_FOUND: Code doesn't exist
        - ROOM_CLOSED: Room is closed
        - ROOM_IN_GAME: Room in game and user is not a member
        """
        try:
            response = await (
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

            # Check if room is in game and user is not a member
            if status == "in_game" and not await self._is_user_room_member(room_id, user_id):
                return None, "ROOM_IN_GAME"

            return room_id, None

        except Exception as e:
            logger.warning("Error resolving room code %s: %s", code, e)
            return None, "ROOM_NOT_FOUND"

    async def _is_user_room_member(self, room_id: str, user_id: str) -> bool:
        """Check if a user is a member (seated) in a room."""
        try:
            response = await (
                self._supabase.table("room_seats")
                .select("room_id")
                .eq("room_id", room_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            logger.warning("Error checking room membership for user %s: %s", user_id, e)
            return False

    async def validate_room_access(
        self, user_id: str, room_code: str
    ) -> tuple[str | None, str | None]:
        """Validate user can access room via WebSocket.

        Checks that:
        1. Room exists with given code and is not closed
        2. User has a seat in the room

        Args:
            user_id: The user attempting to access.
            room_code: The 6-character room code.

        Returns:
            Tuple of (room_id, error_code). One will always be None.
            - On success: (room_id, None)
            - On failure: (None, error_code)

        Error codes:
            - ROOM_NOT_FOUND: Room code doesn't exist or room is closed
            - ROOM_ACCESS_DENIED: User doesn't have a seat in the room
        """
        try:
            # 1. Find room by code (must be open or in_game)
            response = await (
                self._supabase.table("rooms")
                .select("room_id, status")
                .eq("code", room_code.upper())
                .in_("status", ["open", "in_game"])
                .single()
                .execute()
            )

            if not response.data:
                return None, "ROOM_NOT_FOUND"

            room_id = str(response.data["room_id"])

            # 2. Check user has a seat in the room
            if not await self._is_user_room_member(room_id, user_id):
                return None, "ROOM_ACCESS_DENIED"

            return room_id, None

        except Exception as e:
            logger.warning("Error validating room access for code %s: %s", room_code, e)
            return None, "ROOM_NOT_FOUND"

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
            room_id, error_code = await self._resolve_room_code(room_code, user_id)
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
            display_name = await self._get_user_display_name(user_id)

            # Update DB first
            db_updated = await self._update_seat_in_db(room_id, empty_seat_index, user_id)
            if not db_updated:
                return JoinRoomResult(
                    success=False,
                    error_code="INTERNAL_ERROR",
                    error_message="Failed to allocate seat",
                )

            # Update Redis; if this fails, roll back the DB seat allocation
            try:
                await self._update_seat_in_redis(
                    room_id=room_id,
                    seat_index=empty_seat_index,
                    user_id=user_id,
                    display_name=display_name,
                    is_host=False,
                    connected=True,
                )
            except Exception as exc:  # pragma: no cover - defensive error handling
                logger.exception(
                    "Failed to update Redis for room %s seat %d after DB update; attempting rollback",
                    room_id,
                    empty_seat_index,
                )
                rollback_ok = await self._update_seat_in_db(room_id, empty_seat_index, None)
                if not rollback_ok:
                    logger.error(
                        "Failed to rollback DB seat allocation for room %s seat %d after Redis failure",
                        room_id,
                        empty_seat_index,
                    )
                return JoinRoomResult(
                    success=False,
                    error_code="INTERNAL_ERROR",
                    error_message="Failed to allocate seat",
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

    async def _update_seat_in_db(self, room_id: str, seat_index: int, user_id: str | None) -> bool:
        """Update a seat in the database.
        
        If user_id is None, clears the seat (for rollback).
        Otherwise, assigns the seat to the user (optimistic lock).
        """
        try:
            if user_id is None:
                # Rollback: clear the seat without optimistic lock check
                response = await (
                    self._supabase.table("room_seats")
                    .update({"user_id": None})
                    .eq("room_id", room_id)
                    .eq("seat_index", seat_index)
                    .execute()
                )
            else:
                # Normal assignment: only update if seat is empty (optimistic lock)
                response = await (
                    self._supabase.table("room_seats")
                    .update({"user_id": user_id})
                    .eq("room_id", room_id)
                    .eq("seat_index", seat_index)
                    .is_("user_id", "null")
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
        """Update the connected status of a seat in Redis using atomic Lua script."""
        seats_key = self._redis_room_seats_key(room_id)

        # Lua script for atomic read-modify-write
        lua_script = """
        local seat_json = redis.call('HGET', KEYS[1], ARGV[1])
        if not seat_json or seat_json == '' then
            return 0
        end
        local seat = cjson.decode(seat_json)
        seat['connected'] = ARGV[2] == 'true'
        redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(seat))
        return 1
        """

        try:
            await self._redis.eval(
                lua_script,
                keys=[seats_key],
                args=[f"seat:{seat_index}", "true" if connected else "false"],
            )
        except Exception as e:
            logger.warning("Failed to update seat connected atomically: %s", e)
            # Fallback to non-atomic update
            seat_json = await self._redis.hget(seats_key, f"seat:{seat_index}")
            if seat_json:
                try:
                    seat_data = json.loads(seat_json)
                    seat_data["connected"] = connected
                    await self._redis.hset(seats_key, f"seat:{seat_index}", json.dumps(seat_data))
                except json.JSONDecodeError:
                    # Ignore invalid JSON in seat data; atomic update already attempted
                    pass

    async def _update_seat_ready(self, room_id: str, seat_index: int, ready_state: str) -> None:
        """Update the ready status of a seat in Redis using atomic Lua script."""
        seats_key = self._redis_room_seats_key(room_id)

        # Lua script for atomic read-modify-write
        lua_script = """
        local seat_json = redis.call('HGET', KEYS[1], ARGV[1])
        if not seat_json or seat_json == '' then
            return 0
        end
        local seat = cjson.decode(seat_json)
        seat['ready'] = ARGV[2]
        redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(seat))
        return 1
        """

        try:
            await self._redis.eval(
                lua_script,
                keys=[seats_key],
                args=[f"seat:{seat_index}", ready_state],
            )
        except Exception as e:
            logger.warning("Failed to update seat ready atomically: %s", e)
            # Fallback to non-atomic update
            seat_json = await self._redis.hget(seats_key, f"seat:{seat_index}")
            if seat_json:
                try:
                    seat_data = json.loads(seat_json)
                    seat_data["ready"] = ready_state
                    await self._redis.hset(seats_key, f"seat:{seat_index}", json.dumps(seat_data))
                except json.JSONDecodeError:
                    # Ignore invalid JSON in seat data; atomic update already attempted
                    pass

    async def _check_all_ready(self, room_id: str) -> bool:
        """Check if all occupied seats are ready with minimum 2 players.

        Returns True if:
        - At least 2 players are seated
        - All seated players have ready="ready"
        """
        snapshot = await self.get_room_snapshot(room_id)
        if not snapshot:
            return False

        occupied_seats = [s for s in snapshot.seats if s.user_id is not None]
        if len(occupied_seats) < 2:
            return False

        return all(s.ready == "ready" for s in occupied_seats)

    async def _update_room_status(self, room_id: str, status: str) -> None:
        """Update the room status in Redis."""
        meta_key = self._redis_room_meta_key(room_id)
        await self._redis.hset(meta_key, "status", status)

    async def _increment_room_version(self, room_id: str) -> int:
        """Increment the room version counter and return the new version."""
        meta_key = self._redis_room_meta_key(room_id)
        new_version = await self._redis.hincrby(meta_key, "version", 1)
        return int(new_version) if new_version else 0

    async def update_seat_connected_by_user(
        self, room_id: str, user_id: str, connected: bool
    ) -> None:
        """Update connected status for a user's seat in a room.

        Finds the seat occupied by the user and updates its connected status.

        Args:
            room_id: The room ID.
            user_id: The user whose seat to update.
            connected: Whether the user is connected.
        """
        try:
            # Get room snapshot to find user's seat
            snapshot = await self.get_room_snapshot(room_id)
            if not snapshot:
                logger.warning("Room %s not found for seat connected update", room_id)
                return

            # Find user's seat
            for seat in snapshot.seats:
                if seat.user_id == user_id:
                    await self._update_seat_connected(room_id, seat.seat_index, connected)
                    logger.debug(
                        "Updated connected=%s for user %s in room %s seat %d",
                        connected,
                        user_id,
                        room_id,
                        seat.seat_index,
                    )
                    return

            logger.warning("User %s not found in room %s for connected update", user_id, room_id)

        except Exception as e:
            logger.error(
                "Error updating seat connected for user %s in room %s: %s",
                user_id,
                room_id,
                e,
            )

    async def toggle_ready(self, room_id: str, user_id: str) -> ToggleReadyResult:
        """Toggle ready state for a user in a room.

        Logic:
        1. Get room snapshot
        2. Find user's seat (error if not seated)
        3. Check room status is "open" or "ready_to_start" (error if in_game/closed)
        4. Toggle: "not_ready" <-> "ready"
        5. Update seat in Redis
        6. Check if all occupied seats ready (with min 2 players)
        7. Update room status: all_ready -> "ready_to_start", not all_ready -> "open"
        8. Increment room version
        9. Return result

        Args:
            room_id: The room to toggle ready in.
            user_id: The user toggling ready.

        Returns:
            ToggleReadyResult with new ready state and whether room status changed.
        """
        try:
            # Get room snapshot
            snapshot = await self.get_room_snapshot(room_id)
            if not snapshot:
                return ToggleReadyResult(
                    success=False,
                    error_code="ROOM_NOT_FOUND",
                    error_message="Room not found",
                )

            # Find user's seat
            user_seat = None
            for seat in snapshot.seats:
                if seat.user_id == user_id:
                    user_seat = seat
                    break

            if user_seat is None:
                return ToggleReadyResult(
                    success=False,
                    error_code="NOT_SEATED",
                    error_message="You don't have a seat in this room",
                )

            # Check room status allows ready toggle
            if snapshot.status not in ("open", "ready_to_start"):
                return ToggleReadyResult(
                    success=False,
                    error_code="INVALID_ROOM_STATE",
                    error_message=f"Cannot toggle ready in room with status '{snapshot.status}'",
                )

            # Toggle ready state
            new_ready_state = "ready" if user_seat.ready == "not_ready" else "not_ready"

            # Update seat in Redis
            await self._update_seat_ready(room_id, user_seat.seat_index, new_ready_state)

            # Check if all occupied seats are ready
            all_ready = await self._check_all_ready(room_id)

            # Determine new room status
            old_status = snapshot.status
            new_status = "ready_to_start" if all_ready else "open"
            room_status_changed = old_status != new_status

            # Update room status if changed
            if room_status_changed:
                await self._update_room_status(room_id, new_status)

            # Increment room version
            await self._increment_room_version(room_id)

            logger.info(
                "User %s toggled ready to %s in room %s (room status: %s -> %s)",
                user_id,
                new_ready_state,
                room_id,
                old_status,
                new_status,
            )

            return ToggleReadyResult(
                success=True,
                new_ready_state=new_ready_state,
                room_status_changed=room_status_changed,
            )

        except Exception as e:
            logger.exception(
                "Error toggling ready for user %s in room %s: %s",
                user_id,
                room_id,
                e,
            )
            return ToggleReadyResult(
                success=False,
                error_code="INTERNAL_ERROR",
                error_message="Failed to toggle ready state",
            )

    async def reset_ready_on_disconnect(self, room_id: str, user_id: str) -> bool:
        """Reset ready state for a user when they disconnect.

        Also checks if room status needs to revert to "open" if it was "ready_to_start".

        Args:
            room_id: The room the user disconnected from.
            user_id: The user who disconnected.

        Returns:
            True if the room state was modified and a broadcast is needed.
        """
        try:
            # Get room snapshot
            snapshot = await self.get_room_snapshot(room_id)
            if not snapshot:
                return False

            # Find user's seat
            user_seat = None
            for seat in snapshot.seats:
                if seat.user_id == user_id:
                    user_seat = seat
                    break

            if user_seat is None:
                return False

            # Only reset if user was actually ready
            if user_seat.ready != "ready":
                return False

            # Reset ready state
            await self._update_seat_ready(room_id, user_seat.seat_index, "not_ready")

            # Check if room status needs to revert
            if snapshot.status == "ready_to_start":
                await self._update_room_status(room_id, "open")
                logger.info(
                    "Room %s reverted to 'open' after user %s disconnected",
                    room_id,
                    user_id,
                )

            # Increment room version
            await self._increment_room_version(room_id)

            logger.info(
                "Reset ready state for user %s in room %s on disconnect",
                user_id,
                room_id,
            )

            return True

        except Exception as e:
            logger.exception(
                "Error resetting ready for user %s in room %s: %s",
                user_id,
                room_id,
                e,
            )
            return False

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

    async def _close_room_in_db(self, room_id: str) -> bool:
        """Set room status to 'closed' in the database.

        Returns True if successful, False otherwise.
        """
        try:
            response = await (
                self._supabase.table("rooms")
                .update({"status": "closed"})
                .eq("room_id", room_id)
                .execute()
            )
            if response.data and len(response.data) > 0:
                logger.info("Room %s closed in DB", room_id)
                return True
            logger.warning("Room %s not found or already closed in DB", room_id)
            return False
        except Exception as e:
            logger.exception("Error closing room %s in DB: %s", room_id, e)
            return False

    async def _clear_seat_in_db(self, room_id: str, seat_index: int) -> bool:
        """Clear a seat in the database (set user_id to null).

        Returns True if successful, False otherwise.
        """
        try:
            response = await (
                self._supabase.table("room_seats")
                .update({"user_id": None})
                .eq("room_id", room_id)
                .eq("seat_index", seat_index)
                .execute()
            )
            if response.data and len(response.data) > 0:
                logger.debug("Seat %d in room %s cleared in DB", seat_index, room_id)
                return True
            logger.warning("Seat %d in room %s not found in DB", seat_index, room_id)
            return False
        except Exception as e:
            logger.exception("Error clearing seat %d in room %s: %s", seat_index, room_id, e)
            return False

    async def _clear_seat_in_redis(self, room_id: str, seat_index: int) -> None:
        """Clear a seat in Redis (set to empty object)."""
        seats_key = self._redis_room_seats_key(room_id)
        await self._redis.hset(seats_key, f"seat:{seat_index}", json.dumps({}))
        logger.debug("Seat %d in room %s cleared in Redis", seat_index, room_id)

    async def _delete_room_redis(self, room_id: str) -> None:
        """Delete all Redis keys for a room."""
        try:
            meta_key = self._redis_room_meta_key(room_id)
            seats_key = self._redis_room_seats_key(room_id)
            presence_key = f"room:{room_id}:presence"
            await self._redis.delete(meta_key, seats_key, presence_key)
            logger.info("Deleted Redis keys for room %s", room_id)
        except Exception as e:
            logger.warning("Failed to delete Redis keys for room %s: %s", room_id, e)

    async def _reset_all_ready_states(self, room_id: str) -> None:
        """Reset all seated players to 'not_ready'."""
        snapshot = await self.get_room_snapshot(room_id)
        if not snapshot:
            return

        for seat in snapshot.seats:
            if seat.user_id is not None and seat.ready == "ready":
                await self._update_seat_ready(room_id, seat.seat_index, "not_ready")

        logger.debug("Reset all ready states in room %s", room_id)

    async def leave_room(self, room_id: str, user_id: str) -> LeaveRoomResult:
        """Handle a user leaving a room.

        Logic:
        1. Get room snapshot, find user's seat
        2. Check if user is host (is_host field)
        3. If host:
           - Close room in DB (status = "closed")
           - Delete all Redis keys for room
           - Return LeaveRoomResult(was_host=True, room_closed=True)
        4. If player:
           - Clear seat in DB (user_id = null)
           - Clear seat in Redis (empty object)
           - Reset all ready states to "not_ready"
           - If room was "ready_to_start", revert to "open"
           - Remove from presence set
           - Increment version
           - Return result with updated snapshot

        Args:
            room_id: The room to leave.
            user_id: The user leaving the room.

        Returns:
            LeaveRoomResult with operation details.
        """
        try:
            # Get room snapshot
            snapshot = await self.get_room_snapshot(room_id)
            if not snapshot:
                return LeaveRoomResult(
                    success=False,
                    error_code="ROOM_NOT_FOUND",
                    error_message="Room not found",
                )

            # Find user's seat
            user_seat = None
            for seat in snapshot.seats:
                if seat.user_id == user_id:
                    user_seat = seat
                    break

            if user_seat is None:
                return LeaveRoomResult(
                    success=False,
                    error_code="NOT_SEATED",
                    error_message="You don't have a seat in this room",
                )

            # Check if user is host
            if user_seat.is_host:
                # Host is leaving - close the room
                await self._close_room_in_db(room_id)
                await self._delete_room_redis(room_id)

                logger.info("Host %s left room %s, room closed", user_id, room_id)

                return LeaveRoomResult(
                    success=True,
                    was_host=True,
                    room_closed=True,
                    room_snapshot=None,
                )

            # Player is leaving - clear their seat
            await self._clear_seat_in_db(room_id, user_seat.seat_index)
            await self._clear_seat_in_redis(room_id, user_seat.seat_index)

            # Reset all ready states
            await self._reset_all_ready_states(room_id)

            # If room was "ready_to_start", revert to "open"
            if snapshot.status == "ready_to_start":
                await self._update_room_status(room_id, "open")
                logger.info("Room %s reverted to 'open' after player %s left", room_id, user_id)

            # Remove from presence set
            await self.remove_presence(user_id, room_id)

            # Increment version
            await self._increment_room_version(room_id)

            # Get updated snapshot
            updated_snapshot = await self.get_room_snapshot(room_id)

            logger.info("Player %s left room %s", user_id, room_id)

            return LeaveRoomResult(
                success=True,
                was_host=False,
                room_closed=False,
                room_snapshot=updated_snapshot,
            )

        except Exception as e:
            logger.exception("Error leaving room %s for user %s: %s", room_id, user_id, e)
            return LeaveRoomResult(
                success=False,
                error_code="INTERNAL_ERROR",
                error_message="Failed to leave room",
            )


# Singleton instance
_room_service: RoomService | None = None


def get_room_service() -> RoomService:
    """Get the singleton RoomService instance."""
    global _room_service
    if _room_service is None:
        _room_service = RoomService()
    return _room_service
