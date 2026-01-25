"""Game engine module - pure functional game logic.

This module provides the core game engine with:
- Action types for explicit user inputs
- Event types for WebSocket broadcasts
- ProcessResult pattern for error handling
- Modular processing logic

Usage:
    from app.services.game.engine import (
        process_action,
        ProcessResult,
        GameAction,
        RollAction,
        MoveAction,
    )

    # Process an action
    result = process_action(state, RollAction(value=6), player_id)

    if result.success:
        new_state = result.state
        events = result.events  # Broadcast these via WebSocket
    else:
        # Handle error
        print(f"Error: {result.error_code} - {result.error_message}")
"""

# Actions - explicit user inputs
from .actions import (
    CaptureChoiceAction,
    GameAction,
    MoveAction,
    RollAction,
    StartGameAction,
    build_action_from_payload,
)

# Events - for WebSocket broadcasts
from .events import (
    AnyGameEvent,
    AwaitingCaptureChoice,
    AwaitingChoice,
    DiceRolled,
    GameEnded,
    GameEvent,
    GameStarted,
    StackDissolved,
    StackFormed,
    StackMoved,
    StackSplit,
    ThreeSixesPenalty,
    TokenCaptured,
    TokenExitedHell,
    TokenMoved,
    TokenReachedHeaven,
    TurnEnded,
    TurnStarted,
)

# Legal moves
from .legal_moves import get_legal_moves, has_any_legal_moves

# Main processing
from .process import check_win_condition, process_action

# Result types
from .validation import ProcessResult, ValidationResult, validate_action

__all__ = [
    # Actions
    "GameAction",
    "RollAction",
    "MoveAction",
    "CaptureChoiceAction",
    "StartGameAction",
    "build_action_from_payload",
    # Events
    "GameEvent",
    "AnyGameEvent",
    "GameStarted",
    "DiceRolled",
    "ThreeSixesPenalty",
    "TokenMoved",
    "TokenExitedHell",
    "TokenReachedHeaven",
    "TokenCaptured",
    "StackFormed",
    "StackDissolved",
    "StackMoved",
    "StackSplit",
    "TurnStarted",
    "TurnEnded",
    "AwaitingChoice",
    "AwaitingCaptureChoice",
    "GameEnded",
    # Processing
    "process_action",
    "check_win_condition",
    # Validation
    "ProcessResult",
    "ValidationResult",
    "validate_action",
    # Legal moves
    "get_legal_moves",
    "has_any_legal_moves",
]
