"""Tests for handle_game_action WebSocket handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ws import MessageType, WSClientMessage
from app.services.websocket.handlers.base import HandlerContext
from app.services.websocket.handlers.game import handle_game_action

USER_ID = "00000000-0000-0000-0000-000000000001"
ROOM_ID = "room-test-123"
CONN_ID = "conn-test-456"
REQUEST_ID = "00000000-0000-0000-0000-aaaaaaaaaaaa"


def _make_context(
    user_id: str = USER_ID,
    authenticated: bool = True,
    room_id: str | None = ROOM_ID,
    connection_exists: bool = True,
    payload: dict | None = None,
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

    if payload is None:
        payload = {"action_type": "roll", "value": 5}

    message = WSClientMessage(
        type=MessageType.GAME_ACTION,
        request_id=REQUEST_ID,
        payload=payload,
    )
    return HandlerContext(
        connection_id=CONN_ID,
        user_id=user_id,
        message=message,
        manager=manager,
    )


def _make_mock_game_state_dict() -> dict:
    """Return a minimal dict that looks like a serialized GameState."""
    return {"phase": "in_progress", "players": [], "mock": True}


def _make_mock_process_result(success: bool = True) -> MagicMock:
    """Create a mock ProcessResult."""
    result = MagicMock()
    result.success = success
    if success:
        result.state = MagicMock()
        result.state.model_dump.return_value = {"phase": "in_progress", "updated": True}
        mock_event = MagicMock()
        mock_event.model_dump.return_value = {"event_type": "dice_rolled", "value": 5}
        result.events = [mock_event]
        result.error_code = None
        result.error_message = None
    else:
        result.state = None
        result.events = []
        result.error_code = "NOT_YOUR_TURN"
        result.error_message = "Wait for your turn"
    return result


class TestHandleGameActionErrors:
    """Test error paths for handle_game_action handler."""

    @pytest.mark.asyncio
    async def test_not_authenticated(self) -> None:
        ctx = _make_context(authenticated=False)
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_AUTHENTICATED"

    @pytest.mark.asyncio
    async def test_no_connection(self) -> None:
        ctx = _make_context(connection_exists=False)
        result = await handle_game_action(ctx)
        assert not result.success
        # require_authenticated fires first when connection is None
        assert result.response.payload["error_code"] == "NOT_AUTHENTICATED"

    @pytest.mark.asyncio
    async def test_no_room_id(self) -> None:
        ctx = _make_context(room_id=None)
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_IN_ROOM"

    @pytest.mark.asyncio
    async def test_invalid_payload(self) -> None:
        ctx = _make_context(payload={})  # Missing action_type
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    async def test_no_game_in_progress(self, mock_get_state: AsyncMock) -> None:
        mock_get_state.return_value = None
        ctx = _make_context()
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "GAME_NOT_FOUND"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    async def test_corrupted_game_state(self, mock_get_state: AsyncMock) -> None:
        mock_get_state.return_value = {"invalid": "data"}

        ctx = _make_context()
        # GameState.model_validate will raise on invalid data (real validation, no mock)
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "INVALID_GAME_STATE"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.build_action_from_payload")
    @patch("app.schemas.game_engine.GameState.model_validate")
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    async def test_invalid_action(
        self,
        mock_get_state: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        mock_get_state.return_value = _make_mock_game_state_dict()
        mock_validate.return_value = MagicMock()
        mock_build.side_effect = ValueError("Unknown action type: bad")

        ctx = _make_context()
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "INVALID_ACTION"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.process_action")
    @patch("app.services.websocket.handlers.game.build_action_from_payload")
    @patch("app.schemas.game_engine.GameState.model_validate")
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    async def test_engine_rejects_action(
        self,
        mock_get_state: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_process: MagicMock,
    ) -> None:
        mock_get_state.return_value = _make_mock_game_state_dict()
        mock_validate.return_value = MagicMock()
        mock_build.return_value = MagicMock()
        mock_process.return_value = _make_mock_process_result(success=False)

        ctx = _make_context()
        result = await handle_game_action(ctx)
        assert not result.success
        assert result.response.type == MessageType.GAME_ERROR
        assert result.response.payload["error_code"] == "NOT_YOUR_TURN"
        assert result.broadcast is None


class TestHandleGameActionSuccess:
    """Test happy paths for handle_game_action handler."""

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.game.process_action")
    @patch("app.services.websocket.handlers.game.build_action_from_payload")
    @patch("app.schemas.game_engine.GameState.model_validate")
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    async def test_happy_path_roll(
        self,
        mock_get_state: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_process: MagicMock,
        mock_save: AsyncMock,
    ) -> None:
        mock_get_state.return_value = _make_mock_game_state_dict()
        mock_validate.return_value = MagicMock()
        mock_build.return_value = MagicMock()
        mock_process.return_value = _make_mock_process_result(success=True)

        ctx = _make_context(payload={"action_type": "roll", "value": 5})
        result = await handle_game_action(ctx)

        assert result.success
        assert result.response.type == MessageType.GAME_EVENTS
        assert result.response.request_id == REQUEST_ID
        assert len(result.response.payload["events"]) == 1

        assert result.broadcast is not None
        assert result.broadcast.type == MessageType.GAME_EVENTS
        assert result.broadcast.request_id is None

        assert result.room_id == ROOM_ID
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.game.process_action")
    @patch("app.services.websocket.handlers.game.build_action_from_payload")
    @patch("app.schemas.game_engine.GameState.model_validate")
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    async def test_happy_path_move_with_roll_value(
        self,
        mock_get_state: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_process: MagicMock,
        mock_save: AsyncMock,
    ) -> None:
        mock_get_state.return_value = _make_mock_game_state_dict()
        mock_validate.return_value = MagicMock()
        mock_build.return_value = MagicMock()
        mock_process.return_value = _make_mock_process_result(success=True)

        ctx = _make_context(
            payload={"action_type": "move", "stack_id": "stack_1", "roll_value": 5}
        )
        result = await handle_game_action(ctx)

        assert result.success

        # Verify the action_dict passed to build_action_from_payload
        call_args = mock_build.call_args[0][0]
        assert call_args["action_type"] == "move"
        assert call_args["stack_id"] == "stack_1"
        assert call_args["roll_value"] == 5
