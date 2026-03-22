"""Game state storage backed by Redis.

Stores serialized GameState dicts in Redis with a 6-hour TTL.
Key pattern: room:{room_id}:game_state
"""

import json
import logging

from app.dependencies.redis import get_redis_client

logger = logging.getLogger(__name__)

GAME_STATE_TTL = 21600  # 6 hours in seconds


def _key(room_id: str) -> str:
    return f"room:{room_id}:game_state"


async def get_game_state(room_id: str) -> dict | None:
    """Get game state for a room from Redis.

    Returns None if not found or on Redis error.
    """
    try:
        redis = get_redis_client()
        data = await redis.get(_key(room_id))
        if data is None:
            return None
        return json.loads(data)
    except Exception:
        logger.exception("Failed to get game state for room %s", room_id)
        return None


async def save_game_state(room_id: str, state: dict) -> None:
    """Save game state for a room to Redis with TTL.

    Raises on Redis error so callers can handle write failures.
    """
    redis = get_redis_client()
    await redis.set(_key(room_id), json.dumps(state), ex=GAME_STATE_TTL)
    logger.debug("Game state saved for room %s", room_id)


async def delete_game_state(room_id: str) -> None:
    """Delete game state for a room from Redis."""
    try:
        redis = get_redis_client()
        await redis.delete(_key(room_id))
        logger.debug("Game state deleted for room %s", room_id)
    except Exception:
        logger.exception("Failed to delete game state for room %s", room_id)
