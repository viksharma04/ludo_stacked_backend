"""Tests for handle_start_game WebSocket handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ws import MessageType, WSClientMessage
from app.services.room.service import RoomSnapshotData, SeatData
from app.services.websocket.handlers.base import HandlerContext
from app.services.websocket.handlers.start_game import handle_start_game

PLAYER_3_ID = "00000000-0000-0000-0000-000000000003"

# Fixed UUIDs
HOST_ID = "00000000-0000-0000-0000-000000000001"
PLAYER_2_ID = "00000000-0000-0000-0000-000000000002"
ROOM_ID = "room-test-123"
CONN_ID = "conn-test-456"


def _make_context(
    user_id: str = HOST_ID,
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

    message = WSClientMessage(
        type=MessageType.START_GAME,
        request_id="00000000-0000-0000-0000-aaaaaaaaaaaa",
        payload=payload,
    )
    return HandlerContext(
        connection_id=CONN_ID,
        user_id=user_id,
        message=message,
        manager=manager,
    )


def _ready_room_snapshot(
    status: str = "ready_to_start",
    host_id: str = HOST_ID,
    include_player2: bool = True,
) -> RoomSnapshotData:
    """Build a RoomSnapshotData with host and optionally a second player."""
    seats = [
        SeatData(
            seat_index=0,
            user_id=host_id,
            display_name="Host",
            ready="ready",
            connected=True,
            is_host=True,
        ),
    ]
    if include_player2:
        seats.append(
            SeatData(
                seat_index=1,
                user_id=PLAYER_2_ID,
                display_name="Player 2",
                ready="ready",
                connected=True,
                is_host=False,
            ),
        )
    # Fill remaining seats as empty
    for i in range(len(seats), 4):
        seats.append(SeatData(seat_index=i))

    return RoomSnapshotData(
        room_id=ROOM_ID,
        code="ABC123",
        status=status,
        visibility="private",
        ruleset_id="classic",
        max_players=4,
        seats=seats,
        version=1,
    )


class TestHandleStartGameErrors:
    """Test error paths for handle_start_game handler."""

    @pytest.mark.asyncio
    async def test_not_authenticated(self) -> None:
        ctx = _make_context(authenticated=False)
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response is not None
        assert result.response.payload["error_code"] == "NOT_AUTHENTICATED"

    @pytest.mark.asyncio
    async def test_no_connection(self) -> None:
        ctx = _make_context(connection_exists=False)
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response is not None
        # require_authenticated fires first when connection is None
        assert result.response.payload["error_code"] == "NOT_AUTHENTICATED"

    @pytest.mark.asyncio
    async def test_no_room_id(self) -> None:
        ctx = _make_context(room_id=None)
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_IN_ROOM"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_room_not_found(self, mock_get_room_service: MagicMock) -> None:
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = None
        mock_get_room_service.return_value = mock_service

        ctx = _make_context()
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "ROOM_NOT_FOUND"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_user_not_seated(self, mock_get_room_service: MagicMock) -> None:
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_get_room_service.return_value = mock_service

        # Use a user_id that doesn't match any seat
        ctx = _make_context(user_id="00000000-0000-0000-0000-999999999999")
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_SEATED"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_not_host(self, mock_get_room_service: MagicMock) -> None:
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_get_room_service.return_value = mock_service

        # Player 2 is not the host
        ctx = _make_context(user_id=PLAYER_2_ID)
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "NOT_HOST"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_room_status_open(self, mock_get_room_service: MagicMock) -> None:
        snapshot = _ready_room_snapshot(status="open")
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_get_room_service.return_value = mock_service

        ctx = _make_context()
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "PLAYERS_NOT_READY"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_room_status_in_game(self, mock_get_room_service: MagicMock) -> None:
        snapshot = _ready_room_snapshot(status="in_game")
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_get_room_service.return_value = mock_service

        ctx = _make_context()
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "GAME_ALREADY_STARTED"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_game_already_exists(
        self, mock_get_room_service: MagicMock, mock_get_game_state: AsyncMock
    ) -> None:
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_get_room_service.return_value = mock_service

        mock_get_game_state.return_value = {"some": "state"}

        ctx = _make_context()
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "GAME_ALREADY_STARTED"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_fewer_than_two_players(
        self, mock_get_room_service: MagicMock, mock_get_game_state: AsyncMock
    ) -> None:
        snapshot = _ready_room_snapshot(include_player2=False)
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context()
        result = await handle_start_game(ctx)
        assert not result.success
        assert result.response.payload["error_code"] == "GAME_INIT_FAILED"


class TestHandleStartGameSuccess:
    """Test happy path for handle_start_game handler."""

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_happy_path(
        self,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
    ) -> None:
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context()
        result = await handle_start_game(ctx)

        assert result.success
        assert result.response is not None
        assert result.response.type == MessageType.GAME_STARTED
        assert result.response.request_id == ctx.message.request_id
        assert "game_state" in result.response.payload
        assert "events" in result.response.payload

        assert result.broadcast is not None
        assert result.broadcast.type == MessageType.GAME_STARTED
        assert result.broadcast.request_id is None  # Broadcast has no request_id

        assert result.room_id == ROOM_ID

        mock_save_game_state.assert_called_once()
        mock_service.update_room_status_to_in_game.assert_called_once_with(ROOM_ID)


class TestHandleStartGameSettings:
    """Test game settings passed via start_game payload."""

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_default_settings_when_no_payload(
        self,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
    ) -> None:
        """When no payload is sent, defaults are used (grid_length=6, get_out_rolls=[6])."""
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context()  # no payload
        result = await handle_start_game(ctx)

        assert result.success
        game_state = result.response.payload["game_state"]
        assert game_state["board_setup"]["get_out_rolls"] == [6]
        # grid_length=6 → squares_to_win = 9*6+1 = 55
        assert game_state["board_setup"]["squares_to_win"] == 55

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_custom_grid_length(
        self,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
    ) -> None:
        """Frontend can override grid_length via payload."""
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context(payload={"game_settings": {"grid_length": 8}})
        result = await handle_start_game(ctx)

        assert result.success
        game_state = result.response.payload["game_state"]
        # grid_length=8 → squares_to_win = 9*8+1 = 73
        assert game_state["board_setup"]["squares_to_win"] == 73

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_custom_get_out_rolls(
        self,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
    ) -> None:
        """Frontend can override get_out_rolls via payload."""
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context(payload={"game_settings": {"get_out_rolls": [1, 6]}})
        result = await handle_start_game(ctx)

        assert result.success
        game_state = result.response.payload["game_state"]
        assert game_state["board_setup"]["get_out_rolls"] == [1, 6]

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_invalid_grid_length_rejected(
        self,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
    ) -> None:
        """grid_length < 3 should be rejected."""
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context(payload={"game_settings": {"grid_length": 2}})
        result = await handle_start_game(ctx)

        assert not result.success
        assert result.response.payload["error_code"] == "INVALID_SETTINGS"

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    async def test_empty_payload_uses_defaults(
        self,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
    ) -> None:
        """An empty payload (no game_settings key) uses defaults."""
        snapshot = _ready_room_snapshot()
        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        ctx = _make_context(payload={})
        result = await handle_start_game(ctx)

        assert result.success
        game_state = result.response.payload["game_state"]
        assert game_state["board_setup"]["squares_to_win"] == 55
        assert game_state["board_setup"]["get_out_rolls"] == [6]


class TestStartGameFirstPlayerAutoMove:
    """Test that start_game auto-plays the first player if disconnected."""

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.start_game.get_settings")
    @patch("app.services.websocket.handlers.start_game.auto_play_turn")
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    @patch("app.services.websocket.handlers.start_game.asyncio")
    async def test_auto_plays_first_player_if_disconnected(
        self,
        mock_asyncio: MagicMock,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
        mock_auto_play: MagicMock,
        mock_get_settings: MagicMock,
    ) -> None:
        # Host is connected but first player (host) is disconnected in seat data
        snapshot = RoomSnapshotData(
            room_id=ROOM_ID,
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0,
                    user_id=HOST_ID,
                    display_name="Host",
                    ready="ready",
                    connected=False,  # First player disconnected
                    is_host=True,
                ),
                SeatData(
                    seat_index=1,
                    user_id=PLAYER_2_ID,
                    display_name="Player 2",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
                SeatData(seat_index=2),
                SeatData(seat_index=3),
            ],
            version=1,
        )

        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        # Settings with no grace period for tests
        settings = MagicMock()
        settings.TURN_SKIP_GRACE_PERIOD = 0
        mock_get_settings.return_value = settings

        # asyncio.sleep should be awaitable
        mock_asyncio.sleep = AsyncMock()

        # auto_play_turn returns state where P2 has the turn
        auto_state = MagicMock()
        auto_turn = MagicMock()
        auto_turn.player_id = PLAYER_2_ID
        auto_state.current_turn = auto_turn
        auto_state.phase.value = "in_progress"
        auto_state.players = [MagicMock(), MagicMock()]
        auto_state.model_dump.return_value = {"phase": "in_progress", "auto_played": True}
        auto_event = MagicMock()
        auto_event.event_type = "dice_rolled"
        auto_event.model_dump.return_value = {"event_type": "dice_rolled"}
        turn_started = MagicMock()
        turn_started.event_type = "turn_started"
        turn_started.model_dump.return_value = {"event_type": "turn_started", "auto_played": False}
        mock_auto_play.return_value = (auto_state, [turn_started, auto_event])

        ctx = _make_context()
        result = await handle_start_game(ctx)

        assert result.success
        mock_auto_play.assert_called_once()
        # save_game_state called twice: once for initial state, once for auto-play
        assert mock_save_game_state.call_count == 2


class TestStartGameAutoPlayIntegration:
    """Integration tests: real engine verifies auto_played on correct TurnStarted."""

    @pytest.mark.asyncio
    @patch("app.services.game.auto_play.random.randint", return_value=1)
    @patch("app.services.websocket.handlers.start_game.get_settings")
    @patch("app.services.websocket.handlers.start_game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.start_game.get_room_service")
    @patch("app.services.websocket.handlers.start_game.asyncio")
    async def test_first_player_disconnected_marks_correct_turn_started(
        self,
        mock_asyncio: MagicMock,
        mock_get_room_service: MagicMock,
        mock_get_game_state: AsyncMock,
        mock_save_game_state: AsyncMock,
        mock_get_settings: MagicMock,
        mock_randint: MagicMock,
    ) -> None:
        """First player disconnected: their TurnStarted auto_played, next player's not."""
        snapshot = RoomSnapshotData(
            room_id=ROOM_ID,
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0, user_id=HOST_ID, display_name="Host",
                    ready="ready", connected=False, is_host=True,
                ),
                SeatData(
                    seat_index=1, user_id=PLAYER_2_ID, display_name="Player 2",
                    ready="ready", connected=True, is_host=False,
                ),
                SeatData(seat_index=2),
                SeatData(seat_index=3),
            ],
            version=1,
        )

        mock_service = AsyncMock()
        mock_service.get_room_snapshot.return_value = snapshot
        mock_service.update_room_status_to_in_game = AsyncMock()
        mock_get_room_service.return_value = mock_service
        mock_get_game_state.return_value = None

        settings = MagicMock()
        settings.TURN_SKIP_GRACE_PERIOD = 0
        mock_get_settings.return_value = settings
        mock_asyncio.sleep = AsyncMock()

        ctx = _make_context()
        result = await handle_start_game(ctx)

        assert result.success

        all_events = result.broadcast.payload["events"]
        turn_started = [e for e in all_events if e.get("event_type") == "turn_started"]

        # Host (first player) was auto-played → their TurnStarted marked
        host_ts = [ts for ts in turn_started if ts["player_id"] == HOST_ID]
        assert len(host_ts) == 1
        assert host_ts[0]["auto_played"] is True

        # Player 2 is connected → their TurnStarted NOT marked
        p2_ts = [ts for ts in turn_started if ts["player_id"] == PLAYER_2_ID]
        assert len(p2_ts) == 1
        assert p2_ts[0]["auto_played"] is not True
