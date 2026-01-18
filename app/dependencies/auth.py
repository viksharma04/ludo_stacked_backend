from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import Settings, get_settings


class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self._jwks_client: PyJWKClient | None = None

    def _get_jwks_client(self, settings: Settings) -> PyJWKClient:
        if self._jwks_client is None:
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

            # Only allow secure asymmetric algorithms
            allowed_algorithms = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
            if algorithm not in allowed_algorithms:
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
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            )


jwt_bearer = JWTBearer()

CurrentUser = Annotated[dict, Depends(jwt_bearer)]


async def get_current_user(token_payload: CurrentUser) -> dict:
    return {
        "id": token_payload.get("sub"),
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


CurrentUserToken = Annotated[str, Depends(get_current_user_token)]
