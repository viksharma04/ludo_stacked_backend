import logging
from dataclasses import dataclass
from time import time

import httpx
import jwt

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of WebSocket authentication."""

    success: bool
    payload: dict | None = None
    error: str | None = None
    expired: bool = False


class AsyncJWKSClient:
    """Async JWKS client using httpx with TTL-based caching.

    This replaces the sync PyJWKClient to avoid blocking the event loop
    during JWKS fetches.
    """

    def __init__(self, jwks_url: str, cache_ttl: int = 300):
        self.jwks_url = jwks_url
        self.cache_ttl = cache_ttl
        self._jwks_cache: dict | None = None
        self._cache_time: float = 0
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def _get_jwks(self) -> dict:
        """Fetch JWKS from the URL with caching."""
        if self._jwks_cache and time() - self._cache_time < self.cache_ttl:
            return self._jwks_cache

        client = await self._get_http_client()
        response = await client.get(self.jwks_url)
        response.raise_for_status()
        self._jwks_cache = response.json()
        self._cache_time = time()
        logger.debug("JWKS cache refreshed from %s", self.jwks_url)
        return self._jwks_cache

    async def get_signing_key(self, token: str) -> object:
        """Get the signing key for a JWT token.

        Supports RSA, EC (ECDSA), and OKP (EdDSA) key types.

        Args:
            token: The JWT token to get the signing key for.

        Returns:
            The signing key object.

        Raises:
            ValueError: If the key is not found in JWKS or key type is unsupported.
        """
        jwks = await self._get_jwks()
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                kty = key_data.get("kty")
                if kty == "RSA":
                    return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
                elif kty == "EC":
                    return jwt.algorithms.ECAlgorithm.from_jwk(key_data)
                elif kty == "OKP":
                    # OKP is used for EdDSA (Ed25519, Ed448)
                    return jwt.algorithms.OKPAlgorithm.from_jwk(key_data)
                else:
                    raise ValueError(f"Unsupported key type: {kty}")

        raise ValueError(f"Key {kid} not found in JWKS")

    async def close(self) -> None:
        """Close the httpx client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None


class WSAuthenticator:
    """WebSocket token authenticator.

    Validates JWT tokens against Supabase JWKS for WebSocket connections.
    Unlike HTTP auth, returns AuthResult instead of raising exceptions
    to allow graceful handling of auth failures in WebSocket context.
    """

    ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"]

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._jwks_client: AsyncJWKSClient | None = None

    def _get_jwks_client(self) -> AsyncJWKSClient:
        if self._jwks_client is None:
            logger.debug(
                "Initializing async JWKS client for WS auth with URL: %s",
                self._settings.supabase_jwks_url,
            )
            self._jwks_client = AsyncJWKSClient(self._settings.supabase_jwks_url)
        return self._jwks_client

    async def validate_token(self, token: str) -> AuthResult:
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
            signing_key = await jwks_client.get_signing_key(token)
            payload = jwt.decode(
                token,
                signing_key,
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

    async def close(self) -> None:
        """Close the underlying JWKS client."""
        if self._jwks_client:
            await self._jwks_client.close()
            self._jwks_client = None


# Global authenticator instance for lifecycle management
_ws_authenticator: WSAuthenticator | None = None


def get_ws_authenticator() -> WSAuthenticator:
    """Get the global WSAuthenticator instance."""
    global _ws_authenticator
    if _ws_authenticator is None:
        _ws_authenticator = WSAuthenticator()
    return _ws_authenticator


async def close_ws_authenticator() -> None:
    """Close the global WSAuthenticator instance."""
    global _ws_authenticator
    if _ws_authenticator:
        await _ws_authenticator.close()
        _ws_authenticator = None
