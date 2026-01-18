import logging
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status

from app.dependencies.auth import CurrentUser, CurrentUserToken
from app.dependencies.supabase import get_authenticated_supabase_client
from app.schemas.profile import ProfileResponse, ProfileUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def get_profile(current_user: CurrentUser, token: CurrentUserToken):
    """Get the current authenticated user's profile."""
    user_id = current_user.get("sub")
    logger.info("GET /profile - user: %s", user_id)

    supabase = get_authenticated_supabase_client(token)
    response = supabase.table("profiles").select("*").eq("id", user_id).execute()

    if not response.data:
        logger.warning("Profile not found for user: %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    profile = cast(dict[str, Any], response.data[0])
    logger.debug("Profile retrieved for user: %s", user_id)
    return ProfileResponse(
        id=profile["id"],
        display_name=profile.get("display_name"),
        avatar_url=profile.get("avatar_url"),
    )


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    current_user: CurrentUser, token: CurrentUserToken, profile_update: ProfileUpdate
):
    """Update the current authenticated user's display name."""
    user_id = current_user.get("sub")
    logger.info(
        "PATCH /profile - user: %s, display_name: %s",
        user_id,
        profile_update.display_name,
    )

    supabase = get_authenticated_supabase_client(token)
    response = (
        supabase.table("profiles")
        .update({"display_name": profile_update.display_name})
        .eq("id", user_id)
        .execute()
    )

    if not response.data:
        logger.warning("Profile update failed - profile not found for user: %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    profile = cast(dict[str, Any], response.data[0])
    logger.info("Profile updated successfully for user: %s", user_id)
    return ProfileResponse(
        id=profile["id"],
        display_name=profile.get("display_name"),
        avatar_url=profile.get("avatar_url"),
    )
