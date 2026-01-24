"""Game service module.

Provides:
- Game initialization (start_game.py)
- Game engine processing (engine/)
"""

# Re-export from engine for convenience
from .engine import (
    GameAction,
    MoveAction,
    ProcessResult,
    RollAction,
    StartGameAction,
    build_action_from_payload,
    process_action,
)
from .start_game import initialize_game, validate_game_settings

__all__ = [
    # Initialization
    "initialize_game",
    "validate_game_settings",
    # Engine
    "GameAction",
    "ProcessResult",
    "RollAction",
    "MoveAction",
    "StartGameAction",
    "process_action",
    "build_action_from_payload",
]
