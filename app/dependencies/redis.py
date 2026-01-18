import logging

from upstash_redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    """Get the singleton async Redis client.

    Returns the existing client if initialized, otherwise creates a new one.
    """
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        logger.info("Initializing Upstash Redis client")
        _redis_client = Redis(
            url=settings.UPSTASH_REDIS_REST_URL,
            token=settings.UPSTASH_REDIS_REST_TOKEN,
        )
        logger.debug("Redis client initialized with URL: %s", settings.UPSTASH_REDIS_REST_URL)
    return _redis_client


async def close_redis_client() -> None:
    """Close the Redis client connection."""
    global _redis_client
    if _redis_client is not None:
        logger.info("Closing Upstash Redis client")
        await _redis_client.close()
        _redis_client = None
        logger.debug("Redis client closed")
