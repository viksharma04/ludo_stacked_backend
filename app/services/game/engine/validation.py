"""Validation layer for game actions and ProcessResult pattern.

Separates validation from processing logic:
- validate_action() checks if an action is valid given current state
- ProcessResult replaces exceptions for control flow
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)

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
    action_type = type(action).__name__
    logger.debug(
        "Validating action: type=%s, player=%s, phase=%s",
        action_type,
        str(player_id)[:8],
        state.phase.value,
    )

    # Handle start game action
    if isinstance(action, StartGameAction):
        if state.phase != GamePhase.NOT_STARTED:
            logger.warning(
                "Validation failed: GAME_ALREADY_STARTED, current_phase=%s",
                state.phase.value,
            )
            return ValidationResult.error(
                "GAME_ALREADY_STARTED",
                "Game has already started",
            )
        logger.debug("StartGameAction validated successfully")
        return ValidationResult.ok()

    # For all other actions, game must be in progress
    if state.phase == GamePhase.NOT_STARTED:
        logger.warning("Validation failed: GAME_NOT_STARTED")
        return ValidationResult.error(
            "GAME_NOT_STARTED",
            "Game has not started yet",
        )

    if state.phase == GamePhase.FINISHED:
        logger.warning("Validation failed: GAME_FINISHED")
        return ValidationResult.error(
            "GAME_FINISHED",
            "Game has already finished",
        )

    # Check it's this player's turn
    if state.current_turn is None:
        logger.warning("Validation failed: NO_ACTIVE_TURN")
        return ValidationResult.error(
            "NO_ACTIVE_TURN",
            "No active turn",
        )

    if state.current_turn.player_id != player_id:
        logger.warning(
            "Validation failed: NOT_YOUR_TURN, current=%s, attempted=%s",
            str(state.current_turn.player_id)[:8],
            str(player_id)[:8],
        )
        return ValidationResult.error(
            "NOT_YOUR_TURN",
            "It's not your turn",
        )

    # Validate action type matches expected event
    if isinstance(action, RollAction):
        if state.current_event != CurrentEvent.PLAYER_ROLL:
            logger.warning(
                "Validation failed: INVALID_ACTION (roll), expected=%s, got=%s",
                CurrentEvent.PLAYER_ROLL.value,
                state.current_event.value,
            )
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot roll dice - waiting for a different action",
            )

    elif isinstance(action, MoveAction):
        if state.current_event != CurrentEvent.PLAYER_CHOICE:
            logger.warning(
                "Validation failed: INVALID_ACTION (move), expected=%s, got=%s",
                CurrentEvent.PLAYER_CHOICE.value,
                state.current_event.value,
            )
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot move - waiting for a different action",
            )

        # Check move is in legal moves
        if action.token_or_stack_id not in state.current_turn.legal_moves:
            logger.warning(
                "Validation failed: ILLEGAL_MOVE, requested=%s, legal_moves=%s",
                action.token_or_stack_id,
                state.current_turn.legal_moves,
            )
            return ValidationResult.error(
                "ILLEGAL_MOVE",
                f"'{action.token_or_stack_id}' is not a legal move",
            )

    elif isinstance(action, CaptureChoiceAction):
        if state.current_event != CurrentEvent.CAPTURE_CHOICE:
            logger.warning(
                "Validation failed: INVALID_ACTION (capture_choice), expected=%s, got=%s",
                CurrentEvent.CAPTURE_CHOICE.value,
                state.current_event.value,
            )
            return ValidationResult.error(
                "INVALID_ACTION",
                "Cannot make capture choice - not in capture resolution",
            )

    logger.debug("Action validated successfully: type=%s", action_type)
    return ValidationResult.ok()
