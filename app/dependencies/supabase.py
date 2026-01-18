import logging
from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings

logger = logging.getLogger(__name__)


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
