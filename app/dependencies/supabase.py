import logging
from functools import lru_cache

from supabase import AsyncClient, Client, acreate_client, create_client

from app.config import get_settings

logger = logging.getLogger(__name__)

# Sync client (used for HTTP endpoints)


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    logger.debug("Creating anonymous Supabase client")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_API_KEY)


def get_authenticated_supabase_client(access_token: str) -> Client:
    """Create a Supabase client authenticated with the user's JWT.

    This allows RLS policies that check auth.uid() to work correctly.
    """
    settings = get_settings()
    logger.debug("Creating authenticated Supabase client with user JWT")
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_API_KEY)
    client.postgrest.auth(access_token)
    return client


# Async client (used for WebSocket handlers to avoid blocking)

_async_supabase: AsyncClient | None = None


async def init_async_supabase() -> None:
    """Initialize the global async Supabase client.

    Must be called during app startup (lifespan).
    """
    global _async_supabase
    settings = get_settings()
    logger.debug("Creating async Supabase client")
    _async_supabase = await acreate_client(settings.SUPABASE_URL, settings.SUPABASE_API_KEY)
    logger.info("Async Supabase client initialized")


def get_async_supabase() -> AsyncClient:
    """Get the global async Supabase client.

    Raises:
        RuntimeError: If async client was not initialized.
    """
    if _async_supabase is None:
        raise RuntimeError("Async Supabase client not initialized. Call init_async_supabase first.")
    return _async_supabase


async def close_async_supabase() -> None:
    """Close the async Supabase client and its underlying HTTP connections."""
    global _async_supabase
    if _async_supabase is not None:
        # Close underlying httpx client to prevent connection leaks
        # The AsyncClient wraps httpx AsyncClient which needs explicit closure
        try:
            if hasattr(_async_supabase, "postgrest") and hasattr(
                _async_supabase.postgrest, "session"
            ):
                await _async_supabase.postgrest.session.aclose()
                logger.debug("Closed Postgrest httpx session")
        except Exception as e:
            logger.warning("Error closing Postgrest session: %s", e)

        _async_supabase = None
        logger.info("Async Supabase client closed")
