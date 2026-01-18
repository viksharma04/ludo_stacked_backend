import logging
import sys
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    SUPABASE_URL: str
    SUPABASE_API_KEY: str

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # App config
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    DEBUG: bool = False

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.SUPABASE_URL}/auth/v1/.well-known/jwks.json"


def configure_logging(debug: bool = False) -> None:
    """Configure logging for the application."""
    log_level = logging.DEBUG if debug else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    configure_logging(settings.DEBUG)
    logger.info("Settings loaded successfully")
    logger.debug("Supabase URL: %s", settings.SUPABASE_URL)
    logger.debug("JWKS URL: %s", settings.supabase_jwks_url)
    return settings
