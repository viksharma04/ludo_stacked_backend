import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import WebSocket
from upstash_redis.asyncio import Redis

from app.config import get_settings
from app.dependencies.redis import get_redis_client
from app.schemas.ws import (
    ConnectedPayload,
    MessageType,
    PongPayload,
    WSServerMessage,
)

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    """Represents an active WebSocket connection."""

    connection_id: str
    websocket: WebSocket
    user_id: str
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)


class ConnectionManager:
    """Manages WebSocket connections with local and Redis-backed distributed state.

    Local storage:
        - _connections: connection_id -> Connection
        - _user_connections: user_id -> set of connection_ids

    Redis keys:
        - ws:conn:{connection_id} (Hash) - connection metadata
        - ws:user:{user_id}:connections (Set) - user's connection IDs
        - ws:active_users (Set) - all online user IDs
    """

    def __init__(self, redis_client: Redis | None = None, server_id: str | None = None):
        self._redis = redis_client or get_redis_client()
        self._server_id = server_id or os.getenv("HOSTNAME", str(uuid.uuid4())[:8])
        self._settings = get_settings()

        # Local storage
        self._connections: dict[str, Connection] = {}
        self._user_connections: dict[str, set[str]] = {}

        # Cleanup task
        self._cleanup_task: asyncio.Task | None = None

        logger.info("ConnectionManager initialized with server_id: %s", self._server_id)

    @property
    def server_id(self) -> str:
        return self._server_id

    def _redis_active_users_key(self) -> str:
        return "ws:active_users"

    async def connect(self, websocket: WebSocket, user_id: str) -> Connection:
        """Register a new WebSocket connection.

        Args:
            websocket: The WebSocket instance.
            user_id: The authenticated user's ID.

        Returns:
            The created Connection object.
        """
        connection_id = str(uuid.uuid4())
        now = datetime.utcnow()

        connection = Connection(
            connection_id=connection_id,
            websocket=websocket,
            user_id=user_id,
            connected_at=now,
            last_heartbeat=now,
        )

        # Local storage
        self._connections[connection_id] = connection
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(connection_id)

        # Redis: track user as online
        try:
            await self._redis.sadd(self._redis_active_users_key(), user_id)
        except Exception as e:
            logger.error("Failed to mark user %s online in Redis: %s", user_id, e)

        logger.info(
            "Connection %s established for user %s on server %s",
            connection_id,
            user_id,
            self._server_id,
        )

        # Send connected acknowledgment
        await self.send_to_connection(
            connection_id,
            WSServerMessage(
                type=MessageType.CONNECTED,
                payload=ConnectedPayload(
                    connection_id=connection_id,
                    user_id=user_id,
                    server_id=self._server_id,
                ).model_dump(),
            ),
        )

        return connection

    async def disconnect(self, connection_id: str) -> None:
        """Remove a WebSocket connection from local and Redis storage.

        Args:
            connection_id: The connection to remove.
        """
        connection = self._connections.pop(connection_id, None)
        if connection is None:
            logger.debug("Connection %s not found locally for disconnect", connection_id)
            return

        user_id = connection.user_id

        # Remove from local user connections
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(connection_id)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
                # User has no more connections on this server - remove from Redis
                try:
                    await self._redis.srem(self._redis_active_users_key(), user_id)
                except Exception as e:
                    logger.error("Failed to mark user %s offline in Redis: %s", user_id, e)

        logger.info("Connection %s disconnected for user %s", connection_id, user_id)

    async def heartbeat(self, connection_id: str) -> None:
        """Update the last heartbeat timestamp for a connection.

        Args:
            connection_id: The connection to update.
        """
        connection = self._connections.get(connection_id)
        if connection:
            connection.last_heartbeat = datetime.utcnow()
            logger.debug("Heartbeat updated for connection %s", connection_id)

    async def cleanup_stale_connections(self) -> None:
        """Remove connections that have exceeded the timeout period."""
        now = datetime.utcnow()
        timeout = self._settings.WS_CONNECTION_TIMEOUT
        stale_connections = []

        for conn_id, connection in self._connections.items():
            elapsed = (now - connection.last_heartbeat).total_seconds()
            if elapsed > timeout:
                stale_connections.append(conn_id)
                logger.warning(
                    "Connection %s for user %s is stale (%.1fs since heartbeat)",
                    conn_id,
                    connection.user_id,
                    elapsed,
                )

        for conn_id in stale_connections:
            connection = self._connections.get(conn_id)
            if connection:
                try:
                    await connection.websocket.close(code=1001)
                except Exception as e:
                    logger.debug("Error closing stale websocket %s: %s", conn_id, e)
            await self.disconnect(conn_id)

        if stale_connections:
            logger.info("Cleaned up %d stale connections", len(stale_connections))

    async def start_cleanup_task(self) -> None:
        """Start the periodic cleanup task for stale connections."""
        if self._cleanup_task is not None:
            logger.warning("Cleanup task already running")
            return

        async def cleanup_loop():
            interval = self._settings.WS_HEARTBEAT_INTERVAL
            logger.info("Starting cleanup task with interval %ds", interval)
            while True:
                try:
                    await asyncio.sleep(interval)
                    await self.cleanup_stale_connections()
                except asyncio.CancelledError:
                    logger.info("Cleanup task cancelled")
                    break
                except Exception as e:
                    logger.error("Error in cleanup task: %s", e)

        self._cleanup_task = asyncio.create_task(cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """Stop the periodic cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Cleanup task stopped")

    async def close_all_connections(self) -> None:
        """Close all active WebSocket connections gracefully."""
        logger.info("Closing all %d connections", len(self._connections))
        conn_ids = list(self._connections.keys())
        for conn_id in conn_ids:
            connection = self._connections.get(conn_id)
            if connection:
                try:
                    await connection.websocket.close(code=1001)
                except Exception as e:
                    logger.debug("Error closing websocket %s: %s", conn_id, e)
            await self.disconnect(conn_id)

    async def send_to_connection(
        self, connection_id: str, message: WSServerMessage
    ) -> bool:
        """Send a message to a specific connection.

        Args:
            connection_id: The target connection.
            message: The message to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        connection = self._connections.get(connection_id)
        if connection is None:
            logger.debug("Connection %s not found for sending", connection_id)
            return False

        try:
            await connection.websocket.send_json(message.model_dump(mode="json"))
            return True
        except Exception as e:
            logger.warning("Failed to send to connection %s: %s", connection_id, e)
            await self.disconnect(connection_id)
            return False

    async def send_to_user(self, user_id: str, message: WSServerMessage) -> int:
        """Send a message to all connections of a user on this server.

        Args:
            user_id: The target user.
            message: The message to send.

        Returns:
            Number of connections the message was sent to.
        """
        conn_ids = self._user_connections.get(user_id, set())
        sent = 0
        for conn_id in list(conn_ids):
            if await self.send_to_connection(conn_id, message):
                sent += 1
        return sent

    async def broadcast(self, message: WSServerMessage) -> int:
        """Broadcast a message to all connections on this server.

        Args:
            message: The message to broadcast.

        Returns:
            Number of connections the message was sent to.
        """
        sent = 0
        for conn_id in list(self._connections.keys()):
            if await self.send_to_connection(conn_id, message):
                sent += 1
        return sent

    async def is_user_online(self, user_id: str) -> bool:
        """Check if a user has any active connections across all servers.

        Args:
            user_id: The user to check.

        Returns:
            True if user has at least one active connection.
        """
        try:
            return await self._redis.sismember(self._redis_active_users_key(), user_id)
        except Exception as e:
            logger.error("Failed to check user online status in Redis: %s", e)
            # Fall back to local check
            return user_id in self._user_connections

    def get_connection(self, connection_id: str) -> Connection | None:
        """Get a connection by ID (local only)."""
        return self._connections.get(connection_id)

    def get_user_connection_count(self, user_id: str) -> int:
        """Get the number of local connections for a user."""
        return len(self._user_connections.get(user_id, set()))

    def get_total_connection_count(self) -> int:
        """Get the total number of local connections."""
        return len(self._connections)


# Global manager instance (initialized in lifespan)
_connection_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get the global ConnectionManager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager


def set_connection_manager(manager: ConnectionManager) -> None:
    """Set the global ConnectionManager instance."""
    global _connection_manager
    _connection_manager = manager
