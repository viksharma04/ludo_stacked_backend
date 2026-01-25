"""Game action types - explicit user inputs separated from game state."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RollAction(BaseModel):
    """Player rolls the dice."""

    action_type: Literal["roll"] = "roll"
    value: int = Field(..., ge=1, le=6, description="Dice roll value (1-6)")


class MoveAction(BaseModel):
    """Player selects a token or stack to move."""

    action_type: Literal["move"] = "move"
    token_or_stack_id: str = Field(
        ..., description="ID of the token or stack to move"
    )


class CaptureChoiceAction(BaseModel):
    """Player chooses how to resolve a capture situation."""

    action_type: Literal["capture_choice"] = "capture_choice"
    choice: str = Field(
        ...,
        description="Capture resolution choice: 'stack', 'capture', or specific target ID",
    )


class StartGameAction(BaseModel):
    """Host starts the game from lobby."""

    action_type: Literal["start_game"] = "start_game"


# Union type for all game actions
GameAction = Annotated[
    RollAction | MoveAction | CaptureChoiceAction | StartGameAction,
    Field(discriminator="action_type"),
]


def build_action_from_payload(payload: dict) -> GameAction:
    """Build a typed action from a raw payload dict.

    Args:
        payload: Dict with 'action_type' key and action-specific fields.

    Returns:
        The appropriate GameAction subtype.

    Raises:
        ValueError: If action_type is missing or unknown.
    """
    action_type = payload.get("action_type")

    if action_type == "roll":
        return RollAction.model_validate(payload)
    elif action_type == "move":
        return MoveAction.model_validate(payload)
    elif action_type == "capture_choice":
        return CaptureChoiceAction.model_validate(payload)
    elif action_type == "start_game":
        return StartGameAction.model_validate(payload)
    else:
        raise ValueError(f"Unknown action type: {action_type}")
