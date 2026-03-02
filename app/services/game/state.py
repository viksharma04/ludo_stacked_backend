"""Game state storage.

TODO: Replace with Redis-based game service.
"""

# Placeholder for game state storage - will be replaced with Redis service
_game_states: dict[str, dict] = {}


async def get_game_state(room_id: str) -> dict | None:
    """Get game state for a room from storage."""
    return _game_states.get(room_id)


async def save_game_state(room_id: str, state: dict) -> None:
    """Save game state for a room to storage."""
    _game_states[room_id] = state
