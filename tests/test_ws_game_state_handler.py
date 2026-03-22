"""Tests for handle_game_state WebSocket handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ws import MessageType, WSClientMessage
from app.services.websocket.handlers.base import HandlerContext
from app.services.websocket.handlers.game_state import handle_game_state

USER_ID = "00000000-0000-0000-0000-000000000001"
ROOM_ID = "room-test-123"
CONN_ID = "conn-test-456"
REQUEST_ID = "00000000-0000-0000-0000-aaaaaaaaaaaa"


def _make_context(
    user_id: str = USER_ID,
    authenticated: bool = True,
    room_id: str | None = ROOM_ID,
    connection_exists: bool = True,
) -> HandlerContext:
    """Build a HandlerContext with a mocked manager."""
    manager = MagicMock()

    if connection_exists:
        connection = MagicMock()
        connection.authenticated = authenticated
        connection.room_id = room_id
        connection.user_id = user_id
        manager.get_connection.return_value = connection
    else:
        manager.get_connection.return_value = None

    message = WSClientMessage(
        type=MessageType.GAME_STATE,
        request_id=REQUEST_ID,
    )
    return HandlerContext(
        connection_id=CONN_ID,
        user_id=user_id,
        message=message,
        manager=manager,
    )


class TestHandleGameStateErrors:
    @pytest.mark.asyncio
    async def test_not_authenticated(self) -> None:
        ctx = _make_context(authenticated=False)
        result = await handle_game_state(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_AUTHENTICATED"

    @pytest.mark.asyncio
    async def test_not_in_room(self) -> None:
        ctx = _make_context(room_id=None)
        result = await handle_game_state(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_IN_ROOM"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game_state.get_game_state", new_callable=AsyncMock)
    async def test_no_game_in_progress(self, mock_get_state: AsyncMock) -> None:
        mock_get_state.return_value = None
        ctx = _make_context()
        result = await handle_game_state(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "GAME_NOT_FOUND"


class TestHandleGameStateSuccess:
    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game_state.get_game_state", new_callable=AsyncMock)
    async def test_returns_full_game_state(self, mock_get_state: AsyncMock) -> None:
        game_state_dict = {"phase": "in_progress", "players": [{"id": "p1"}]}
        mock_get_state.return_value = game_state_dict

        ctx = _make_context()
        result = await handle_game_state(ctx)

        assert result.success
        assert result.response.type == MessageType.GAME_STATE
        assert result.response.request_id == REQUEST_ID
        assert result.response.payload["game_state"] == game_state_dict
        assert result.broadcast is None  # Not broadcast to room
