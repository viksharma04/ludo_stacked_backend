import logging
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of WebSocket authentication."""

    success: bool
    payload: dict | None = None
    error: str | None = None
    expired: bool = False


class WSAuthenticator:
    """WebSocket token authenticator.

    Validates JWT tokens against Supabase JWKS for WebSocket connections.
    Unlike HTTP auth, returns AuthResult instead of raising exceptions
    to allow graceful handling of auth failures in WebSocket context.
    """

    ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._jwks_client: PyJWKClient | None = None

    def _get_jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            logger.debug(
                "Initializing JWKS client for WS auth with URL: %s",
                self._settings.supabase_jwks_url,
            )
            self._jwks_client = PyJWKClient(self._settings.supabase_jwks_url)
        return self._jwks_client

    def validate_token(self, token: str) -> AuthResult:
        """Validate a JWT token for WebSocket authentication.

        Args:
            token: The JWT token string to validate.

        Returns:
            AuthResult with success=True and payload on valid token,
            or success=False with error message on failure.
        """
        if not token:
            logger.warning("WS auth failed: empty token")
            return AuthResult(success=False, error="Missing token")

        try:
            unverified_header = jwt.get_unverified_header(token)
            algorithm = unverified_header.get("alg")
            logger.debug("WS JWT algorithm: %s", algorithm)

            if algorithm not in self.ALLOWED_ALGORITHMS:
                logger.warning("WS auth failed: disallowed algorithm %s", algorithm)
                return AuthResult(
                    success=False,
                    error=f"Algorithm {algorithm} not allowed",
                )

            jwks_client = self._get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience="authenticated",
            )

            user_id = payload.get("sub")
            logger.debug("WS JWT validated successfully for user: %s", user_id)
            return AuthResult(success=True, payload=payload)

        except jwt.ExpiredSignatureError:
            logger.warning("WS auth failed: token expired")
            return AuthResult(
                success=False,
                error="Token has expired",
                expired=True,
            )
        except jwt.InvalidTokenError as e:
            logger.warning("WS auth failed: invalid token - %s", e)
            return AuthResult(success=False, error=f"Invalid token: {e}")
        except Exception as e:
            logger.error("WS auth unexpected error: %s", e)
            return AuthResult(success=False, error="Authentication failed")
