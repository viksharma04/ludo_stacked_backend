from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    id: str
    display_name: str | None = None
    avatar_url: str | None = None


class ProfileUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)
