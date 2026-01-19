import logging
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self._jwks_client: PyJWKClient | None = None

    def _get_jwks_client(self, settings: Settings) -> PyJWKClient:
        if self._jwks_client is None:
            logger.debug("Initializing JWKS client with URL: %s", settings.supabase_jwks_url)
            self._jwks_client = PyJWKClient(settings.supabase_jwks_url)
        return self._jwks_client

    async def __call__(
        self,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(HTTPBearer(auto_error=False)),
        ],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> dict:
        if credentials is None:
            logger.warning("Authentication failed: missing authorization header")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        try:
            # Get algorithm from token header
            unverified_header = jwt.get_unverified_header(token)
            algorithm = unverified_header.get("alg")
            logger.debug("JWT algorithm: %s", algorithm)

            # Only allow secure asymmetric algorithms
            allowed_algorithms = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
            if algorithm not in allowed_algorithms:
                logger.warning("Authentication failed: disallowed algorithm %s", algorithm)
                raise jwt.InvalidTokenError(
                    f"Algorithm {algorithm} not allowed. Supabase JWKS requires asymmetric signing."
                )

            jwks_client = self._get_jwks_client(settings)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience="authenticated",
            )
            user_id = payload.get("sub")
            logger.debug("JWT validated successfully for user: %s", user_id)
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Authentication failed: token expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            logger.warning("Authentication failed: invalid token - %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            )


jwt_bearer = JWTBearer()


class OptionalJWTBearer(JWTBearer):
    """JWT bearer that returns None instead of raising an error when no token is provided."""

    async def __call__(
        self,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(HTTPBearer(auto_error=False)),
        ],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> dict | None:
        if credentials is None:
            return None

        # Delegate to parent for actual validation
        return await super().__call__(credentials, settings)


optional_jwt_bearer = OptionalJWTBearer()

CurrentUser = Annotated[dict, Depends(jwt_bearer)]
OptionalCurrentUser = Annotated[dict | None, Depends(optional_jwt_bearer)]


async def get_current_user(token_payload: CurrentUser) -> dict:
    user_id = token_payload.get("sub")
    logger.debug("Extracted user from token: %s", user_id)
    return {
        "id": user_id,
        "email": token_payload.get("email"),
        "role": token_payload.get("role"),
        "aud": token_payload.get("aud"),
    }


async def get_current_user_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearer(auto_error=False)),
    ],
) -> str:
    """Get the raw JWT token from the request.

    Raises HTTPException 401 if no token is provided.
    """
    if credentials is None:
        logger.warning("Token extraction failed: missing authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.debug("Token extracted from request")
    return credentials.credentials


CurrentUserToken = Annotated[str, Depends(get_current_user_token)]
