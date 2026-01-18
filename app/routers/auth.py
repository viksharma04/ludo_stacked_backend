import logging

from fastapi import APIRouter

from app.dependencies.auth import CurrentUser
from app.schemas.auth import AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthUser)
async def get_me(current_user: CurrentUser):
    """Get the current authenticated user's profile."""
    user_id = current_user.get("sub")
    logger.info("GET /auth/me - user: %s", user_id)
    return AuthUser(
        id=user_id,
        email=current_user.get("email"),
    )
