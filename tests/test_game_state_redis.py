"""Tests for Redis-backed game state storage."""

import json
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Player,
    Stack,
    StackState,
    Turn,
)
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


@pytest.mark.asyncio
@patch("app.services.game.state.get_redis_client")
async def test_save_game_state_with_real_game_state(mock_get_redis: AsyncMock) -> None:
    """Verify that a real GameState serializes correctly for Redis storage.

    model_dump(mode='json') must be used to convert UUIDs/enums to JSON-safe types.
    """
    mock_redis = AsyncMock()
    mock_get_redis.return_value = mock_redis

    player = Player(
        player_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="P1",
        color="red",
        turn_order=1,
        abs_starting_index=0,
        stacks=[Stack(stack_id="stack_1", state=StackState.HELL, height=1, progress=0)],
    )
    board = BoardSetup(
        grid_length=6,
        loop_length=52,
        squares_to_win=55,
        squares_to_homestretch=49,
        starting_positions=[0, 13],
        safe_spaces=[0, 7],
        get_out_rolls=[6],
    )
    turn = Turn(player_id=player.player_id, current_turn_order=1)
    state = GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=board,
        current_turn=turn,
    )

    # This is how handlers should call save_game_state
    state_dict = state.model_dump(mode="json")
    await save_game_state(ROOM_ID, state_dict)

    # Verify json.dumps was called successfully (no TypeError on UUIDs)
    call_args = mock_redis.set.call_args
    stored_json = call_args[0][1]
    parsed = json.loads(stored_json)
    assert parsed["players"][0]["player_id"] == "00000000-0000-0000-0000-000000000001"
    assert parsed["phase"] == "in_progress"
