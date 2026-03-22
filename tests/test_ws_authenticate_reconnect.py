"""Tests for authenticate handler's mid-game reconnection auto-push."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ws import MessageType, WSClientMessage
from app.services.websocket.handlers.authenticate import handle_authenticate
from app.services.websocket.handlers.base import HandlerContext


USER_ID = "00000000-0000-0000-0000-000000000001"
CONN_ID = "conn-test-456"
ROOM_ID = "room-test-123"
ROOM_CODE = "ABC123"
REQUEST_ID = "00000000-0000-0000-0000-aaaaaaaaaaaa"
FAKE_TOKEN = "valid.jwt.token"


def _make_unauthenticated_context() -> HandlerContext:
    """Build a HandlerContext with an unauthenticated connection."""
    manager = MagicMock()
    connection = MagicMock()
    connection.authenticated = False
    connection.user_id = None
    connection.room_id = None
    manager.get_connection.return_value = connection
    manager.authenticate_connection = AsyncMock(return_value=True)
    manager.send_to_connection = AsyncMock(return_value=True)

    message = WSClientMessage(
        type=MessageType.AUTHENTICATE,
        request_id=REQUEST_ID,
        payload={"token": FAKE_TOKEN, "room_code": ROOM_CODE},
    )
    return HandlerContext(
        connection_id=CONN_ID,
        user_id="",
        message=message,
        manager=manager,
    )


def _make_room_snapshot(status: str = "open"):
    """Create a mock room snapshot with given status."""
    snapshot = MagicMock()
    snapshot.room_id = ROOM_ID
    snapshot.code = ROOM_CODE
    snapshot.status = status
    snapshot.visibility = "public"
    snapshot.ruleset_id = "standard"
    snapshot.max_players = 4
    snapshot.version = 1
    seat = MagicMock()
    seat.user_id = USER_ID
    seat.display_name = "Player 1"
    seat.ready = "ready"
    seat.connected = True
    seat.is_host = True
    seat.seat_index = 0
    snapshot.seats = [seat]
    return snapshot


class TestAuthenticateAutoGameState:
    """Test that authenticate handler auto-pushes game state for in_game rooms."""

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.authenticate.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.authenticate.get_room_service")
    @patch("app.services.websocket.handlers.authenticate.get_ws_authenticator")
    async def test_sends_game_state_when_in_game(
        self,
        mock_get_auth: MagicMock,
        mock_get_room: MagicMock,
        mock_get_game_state: AsyncMock,
    ) -> None:
        # Setup auth
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.payload = {"sub": USER_ID}
        mock_get_auth.return_value.validate_token = AsyncMock(return_value=auth_result)

        # Setup room service
        room_service = AsyncMock()
        room_service.validate_room_access.return_value = (ROOM_ID, None)
        room_service.get_room_snapshot.return_value = _make_room_snapshot(status="in_game")
        mock_get_room.return_value = room_service

        # Setup game state
        game_state_dict = {"phase": "in_progress", "players": []}
        mock_get_game_state.return_value = game_state_dict

        ctx = _make_unauthenticated_context()
        result = await handle_authenticate(ctx)

        assert result.success

        # Verify game state was sent to connection
        ctx.manager.send_to_connection.assert_called_once()
        call_args = ctx.manager.send_to_connection.call_args
        assert call_args[0][0] == CONN_ID
        sent_message = call_args[0][1]
        assert sent_message.type == MessageType.GAME_STATE
        assert sent_message.payload["game_state"] == game_state_dict

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.authenticate.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.authenticate.get_room_service")
    @patch("app.services.websocket.handlers.authenticate.get_ws_authenticator")
    async def test_no_game_state_sent_when_lobby(
        self,
        mock_get_auth: MagicMock,
        mock_get_room: MagicMock,
        mock_get_game_state: AsyncMock,
    ) -> None:
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.payload = {"sub": USER_ID}
        mock_get_auth.return_value.validate_token = AsyncMock(return_value=auth_result)

        room_service = AsyncMock()
        room_service.validate_room_access.return_value = (ROOM_ID, None)
        room_service.get_room_snapshot.return_value = _make_room_snapshot(status="open")
        mock_get_room.return_value = room_service

        ctx = _make_unauthenticated_context()
        result = await handle_authenticate(ctx)

        assert result.success
        mock_get_game_state.assert_not_called()
        ctx.manager.send_to_connection.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.authenticate.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.authenticate.get_room_service")
    @patch("app.services.websocket.handlers.authenticate.get_ws_authenticator")
    async def test_auth_succeeds_even_if_game_state_missing(
        self,
        mock_get_auth: MagicMock,
        mock_get_room: MagicMock,
        mock_get_game_state: AsyncMock,
    ) -> None:
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.payload = {"sub": USER_ID}
        mock_get_auth.return_value.validate_token = AsyncMock(return_value=auth_result)

        room_service = AsyncMock()
        room_service.validate_room_access.return_value = (ROOM_ID, None)
        room_service.get_room_snapshot.return_value = _make_room_snapshot(status="in_game")
        mock_get_room.return_value = room_service

        mock_get_game_state.return_value = None  # Game state missing

        ctx = _make_unauthenticated_context()
        result = await handle_authenticate(ctx)

        # Auth still succeeds — game state push is best-effort
        assert result.success
        ctx.manager.send_to_connection.assert_not_called()
