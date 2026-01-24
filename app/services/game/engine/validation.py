"""Validation layer for game actions and ProcessResult pattern.

Separates validation from processing logic:
- validate_action() checks if an action is valid given current state
- ProcessResult replaces exceptions for control flow
"""

from dataclasses import dataclass, field
from uuid import UUID

from app.schemas.game_engine import CurrentEvent, GamePhase, GameState

from .actions import (
    CaptureChoiceAction,
    GameAction,
    MoveAction,
    RollAction,
    StartGameAction,
)
from .events import AnyGameEvent


@dataclass
class ProcessResult:
    """Result of processing a game action.

    Replaces exceptions for control flow, providing explicit success/failure
    with error codes suitable for client localization.
    """

    state: GameState | None = None
    events: list[AnyGameEvent] = field(default_factory=list)
    success: bool = True
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def ok(
        cls,
        state: GameState,
        events: list[AnyGameEvent] | None = None,
    ) -> "ProcessResult":
        """Create a successful result with new state and events."""
        return cls(
            state=state,
            events=events or [],
            success=True,
        )

    @classmethod
    def failure(cls, code: str, message: str) -> "ProcessResult":
        """Create a failure result with error details."""
        return cls(
            state=None,
            events=[],
            success=False,
            error_code=code,
            error_message=message,
        )


@dataclass
class ValidationResult:
    """Result of validating an action before processing."""

    is_valid: bool = True
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def ok(cls) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(is_valid=True)

    @classmethod
    def error(cls, code: str, message: str) -> "ValidationResult":
        """Create a validation failure with error details."""
        return cls(
            is_valid=False,
            error_code=code,
            error_message=message,
        )


def validate_action(
    state: GameState,
    action: GameAction,
    player_id: UUID,
) -> ValidationResult:
    """Validate an action before processing.

    Checks:
    - Game phase allows this action
    - It's the correct player's turn
    - Action type matches expected event
    - For moves, the chosen token/stack is in legal_moves

    Args:
        state: Current game state.
        action: The action to validate.
        player_id: The player attempting the action.

    Returns:
        ValidationResult indicating success or failure with error details.
    """
    # Handle start game action
    if isinstance(action, StartGameAction):
        if state.phase != GamePhase.NOT_STARTED:
            return ValidationResult.error(
                "GAME_ALREADY_STARTED",
                "Game has already started",
            )
        return ValidationResult.ok()

    # For all other actions, game must be in progress
    if state.phase == GamePhase.NOT_STARTED:
        return ValidationResult.error(
            "GAME_NOT_STARTED",
            "Game has not started yet",
        )

    if state.phase == GamePhase.FINISHED:
        return ValidationResult.error(
            "GAME_FINISHED",
            "Game has already finished",
        )

    # Check it's this player's turn
    if state.current_turn is None:
        return ValidationResult.error(
            "NO_ACTIVE_TURN",
            "No active turn",
        )

    if state.current_turn.player_id != player_id:
        return ValidationResult.error(
            "NOT_YOUR_TURN",
            "It's not your turn",
        )

    # Validate action type matches expected event
    if isinstance(action, RollAction):
        if state.current_event != CurrentEvent.PLAYER_ROLL:
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot roll dice - waiting for a different action",
            )

    elif isinstance(action, MoveAction):
        if state.current_event != CurrentEvent.PLAYER_CHOICE:
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot move - waiting for a different action",
            )

        # Check move is in legal moves
        if action.token_or_stack_id not in state.current_turn.legal_moves:
            return ValidationResult.error(
                "ILLEGAL_MOVE",
                f"'{action.token_or_stack_id}' is not a legal move",
            )

    elif isinstance(action, CaptureChoiceAction):
        if state.current_event != CurrentEvent.CAPTURE_CHOICE:
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot make capture choice - not in capture resolution",
            )

    return ValidationResult.ok()
