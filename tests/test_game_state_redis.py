"""Tests for Redis-backed game state storage."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.game.state import (
    GAME_STATE_TTL,
    delete_game_state,
    get_game_state,
    save_game_state,
)

ROOM_ID = "room-test-123"
SAMPLE_STATE = {"phase": "in_progress", "players": [], "board_setup": {}}


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_save_game_state_writes_json_with_ttl(mock_get_redis: AsyncMock) -> None:
    mock_redis = AsyncMock()
    mock_get_redis.return_value = mock_redis

    await save_game_state(ROOM_ID, SAMPLE_STATE)

    mock_redis.set.assert_called_once_with(
        f"room:{ROOM_ID}:game_state",
        json.dumps(SAMPLE_STATE),
        ex=GAME_STATE_TTL,
    )


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_get_game_state_returns_parsed_json(mock_get_redis: AsyncMock) -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(SAMPLE_STATE)
    mock_get_redis.return_value = mock_redis

    result = await get_game_state(ROOM_ID)

    assert result == SAMPLE_STATE
    mock_redis.get.assert_called_once_with(f"room:{ROOM_ID}:game_state")


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_get_game_state_returns_none_when_not_found(mock_get_redis: AsyncMock) -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_get_redis.return_value = mock_redis

    result = await get_game_state(ROOM_ID)
    assert result is None


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_get_game_state_returns_none_on_redis_error(mock_get_redis: AsyncMock) -> None:
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = Exception("Redis connection failed")
    mock_get_redis.return_value = mock_redis

    result = await get_game_state(ROOM_ID)
    assert result is None


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_save_game_state_raises_on_redis_error(mock_get_redis: AsyncMock) -> None:
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = Exception("Redis connection failed")
    mock_get_redis.return_value = mock_redis

    with pytest.raises(Exception, match="Redis connection failed"):
        await save_game_state(ROOM_ID, SAMPLE_STATE)


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_delete_game_state(mock_get_redis: AsyncMock) -> None:
    mock_redis = AsyncMock()
    mock_get_redis.return_value = mock_redis

    await delete_game_state(ROOM_ID)

    mock_redis.delete.assert_called_once_with(f"room:{ROOM_ID}:game_state")
