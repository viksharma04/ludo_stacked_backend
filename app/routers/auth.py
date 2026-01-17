from fastapi import APIRouter

from app.dependencies.auth import CurrentUser
from app.schemas.auth import AuthUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthUser)
async def get_me(current_user: CurrentUser):
    """Get the current authenticated user's profile."""
    return AuthUser(
        id=current_user.get("sub"),
        email=current_user.get("email"),
    )
