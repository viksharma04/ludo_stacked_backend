"""Tests for handle_game_action WebSocket handler."""

from unittest.mock import AsyncMock, MagicMock, patch
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
from app.schemas.ws import MessageType, WSClientMessage
from app.services.websocket.handlers.base import HandlerContext
from app.services.websocket.handlers.game import (
    _auto_play_disconnected_turns,
    handle_game_action,
)

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

        ctx = _make_context(payload={"action_type": "move", "stack_id": "stack_1", "roll_value": 5})
        result = await handle_game_action(ctx)

        assert result.success

        # Verify the action_dict passed to build_action_from_payload
        call_args = mock_build.call_args[0][0]
        assert call_args["action_type"] == "move"
        assert call_args["stack_id"] == "stack_1"
        assert call_args["roll_value"] == 5


class TestHandleGameActionAutoMove:
    """Test auto-move for disconnected players after action processing."""

    @pytest.mark.asyncio
    @patch("app.services.websocket.handlers.game.get_settings")
    @patch("app.services.websocket.handlers.game.get_room_service")
    @patch("app.services.websocket.handlers.game.auto_play_turn")
    @patch("app.services.websocket.handlers.game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.game.process_action")
    @patch("app.services.websocket.handlers.game.build_action_from_payload")
    @patch("app.schemas.game_engine.GameState.model_validate")
    @patch("app.services.websocket.handlers.game.get_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.game.asyncio")
    async def test_auto_plays_disconnected_player_after_grace(
        self,
        mock_asyncio: MagicMock,
        mock_get_state: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_process: MagicMock,
        mock_save: AsyncMock,
        mock_auto_play: MagicMock,
        mock_get_room: MagicMock,
        mock_get_settings: MagicMock,
    ) -> None:
        # Setup: action processes successfully, next player is disconnected
        mock_get_state.return_value = _make_mock_game_state_dict()
        mock_validate.return_value = MagicMock()
        mock_build.return_value = MagicMock()

        # The process result - next player has turn_order=2
        process_result = _make_mock_process_result(success=True)
        current_turn = MagicMock()
        current_turn.player_id = "00000000-0000-0000-0000-000000000002"
        process_result.state.current_turn = current_turn
        process_result.state.phase.value = "in_progress"
        process_result.state.players = [MagicMock(), MagicMock()]  # 2 players
        mock_process.return_value = process_result

        # Room service returns snapshot showing player 2 disconnected
        room_service = AsyncMock()
        seat1 = MagicMock()
        seat1.user_id = USER_ID
        seat1.connected = True
        seat2 = MagicMock()
        seat2.user_id = "00000000-0000-0000-0000-000000000002"
        seat2.connected = False
        snapshot = MagicMock()
        snapshot.seats = [seat1, seat2]
        room_service.get_room_snapshot.return_value = snapshot
        mock_get_room.return_value = room_service

        # Settings
        settings = MagicMock()
        settings.TURN_SKIP_GRACE_PERIOD = 0  # No delay in tests
        mock_get_settings.return_value = settings

        # auto_play_turn returns new state where next player (P1) is connected
        auto_state = MagicMock()
        auto_turn_mock = MagicMock()
        auto_turn_mock.player_id = USER_ID  # Back to P1 who is connected
        auto_state.current_turn = auto_turn_mock
        auto_state.phase.value = "in_progress"
        auto_state.model_dump.return_value = {"phase": "in_progress", "auto_played": True}
        auto_event = MagicMock()
        auto_event.model_dump.return_value = {"event_type": "dice_rolled"}
        auto_event.event_type = "dice_rolled"
        turn_started_event = MagicMock()
        turn_started_event.event_type = "turn_started"
        turn_started_event.model_dump.return_value = {
            "event_type": "turn_started",
            "auto_played": False,
        }
        mock_auto_play.return_value = (auto_state, [turn_started_event, auto_event])

        # asyncio.sleep should be awaitable
        mock_asyncio.sleep = AsyncMock()

        ctx = _make_context()
        result = await handle_game_action(ctx)

        assert result.success
        mock_auto_play.assert_called_once()
        # save_game_state called twice: once for original action, once for auto-play
        assert mock_save.call_count == 2


# --- Helpers for integration tests (real engine, no auto_play_turn mock) ---

P1_UUID = UUID("00000000-0000-0000-0000-000000000001")
P2_UUID = UUID("00000000-0000-0000-0000-000000000002")
P3_UUID = UUID("00000000-0000-0000-0000-000000000003")


def _make_hell_stacks() -> list[Stack]:
    return [
        Stack(stack_id=f"stack_{i}", state=StackState.HELL, height=1, progress=0)
        for i in range(1, 5)
    ]


def _make_two_player_board() -> BoardSetup:
    return BoardSetup(
        grid_length=6,
        loop_length=52,
        squares_to_win=55,
        squares_to_homestretch=49,
        starting_positions=[0, 26],
        safe_spaces=[0, 7, 13, 20, 26, 33, 39, 46],
        get_out_rolls=[6],
    )


class TestAutoPlayIntegration:
    """Integration tests: real engine verifies UUID handling and auto_played marking."""

    @pytest.mark.asyncio
    @patch("app.services.game.auto_play.random.randint", return_value=1)
    @patch("app.services.websocket.handlers.game.get_settings")
    @patch("app.services.websocket.handlers.game.get_room_service")
    @patch("app.services.websocket.handlers.game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.game.asyncio")
    async def test_auto_played_only_on_disconnected_players_turn_started(
        self,
        mock_asyncio: MagicMock,
        mock_save: AsyncMock,
        mock_get_room: MagicMock,
        mock_get_settings: MagicMock,
        mock_randint: MagicMock,
    ) -> None:
        """P2 disconnected: TurnStarted(P1) after auto-play should NOT be auto_played."""
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[
                Player(
                    player_id=P1_UUID, name="P1", color="red", turn_order=1,
                    abs_starting_index=0, stacks=_make_hell_stacks(),
                ),
                Player(
                    player_id=P2_UUID, name="P2", color="blue", turn_order=2,
                    abs_starting_index=26, stacks=_make_hell_stacks(),
                ),
            ],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=_make_two_player_board(),
            current_turn=Turn(
                player_id=P2_UUID, initial_roll=True, rolls_to_allocate=[],
                legal_moves=[], current_turn_order=2, extra_rolls=0,
            ),
            event_seq=10,
        )

        # P2 disconnected, P1 connected
        seat1 = MagicMock(user_id=str(P1_UUID), connected=True)
        seat2 = MagicMock(user_id=str(P2_UUID), connected=False)
        room_service = AsyncMock()
        room_service.get_room_snapshot.return_value = MagicMock(seats=[seat1, seat2])
        mock_get_room.return_value = room_service

        settings = MagicMock()
        settings.TURN_SKIP_GRACE_PERIOD = 0
        mock_get_settings.return_value = settings
        mock_asyncio.sleep = AsyncMock()

        auto_events, auto_played_ids = await _auto_play_disconnected_turns(
            "room-123", state, MagicMock()
        )

        # P2 was auto-played, P1 was not
        assert str(P2_UUID) in auto_played_ids
        assert str(P1_UUID) not in auto_played_ids

        # Real engine produced events (proves UUID was passed correctly, not str)
        assert len(auto_events) > 0

        # TurnStarted(P1) should NOT be auto_played (P1 is connected)
        turn_started = [e for e in auto_events if e.get("event_type") == "turn_started"]
        assert len(turn_started) >= 1
        for ts in turn_started:
            assert ts["auto_played"] is not True, (
                f"TurnStarted for connected player {ts['player_id']} should not be auto_played"
            )

    @pytest.mark.asyncio
    @patch("app.services.game.auto_play.random.randint", return_value=1)
    @patch("app.services.websocket.handlers.game.get_settings")
    @patch("app.services.websocket.handlers.game.get_room_service")
    @patch("app.services.websocket.handlers.game.save_game_state", new_callable=AsyncMock)
    @patch("app.services.websocket.handlers.game.asyncio")
    async def test_consecutive_disconnected_marks_intermediate_not_final(
        self,
        mock_asyncio: MagicMock,
        mock_save: AsyncMock,
        mock_get_room: MagicMock,
        mock_get_settings: MagicMock,
        mock_randint: MagicMock,
    ) -> None:
        """P2+P3 disconnected: TurnStarted(P3) marked auto_played, TurnStarted(P1) not."""
        board = BoardSetup(
            grid_length=6, loop_length=52, squares_to_win=55,
            squares_to_homestretch=49, starting_positions=[0, 13, 26],
            safe_spaces=[0, 7, 13, 20, 26, 33, 39, 46],
            get_out_rolls=[6],
        )
        state = GameState(
            phase=GamePhase.IN_PROGRESS,
            players=[
                Player(
                    player_id=P1_UUID, name="P1", color="red", turn_order=1,
                    abs_starting_index=0, stacks=_make_hell_stacks(),
                ),
                Player(
                    player_id=P2_UUID, name="P2", color="blue", turn_order=2,
                    abs_starting_index=13, stacks=_make_hell_stacks(),
                ),
                Player(
                    player_id=P3_UUID, name="P3", color="green", turn_order=3,
                    abs_starting_index=26, stacks=_make_hell_stacks(),
                ),
            ],
            current_event=CurrentEvent.PLAYER_ROLL,
            board_setup=board,
            current_turn=Turn(
                player_id=P2_UUID, initial_roll=True, rolls_to_allocate=[],
                legal_moves=[], current_turn_order=2, extra_rolls=0,
            ),
            event_seq=10,
        )

        seat1 = MagicMock(user_id=str(P1_UUID), connected=True)
        seat2 = MagicMock(user_id=str(P2_UUID), connected=False)
        seat3 = MagicMock(user_id=str(P3_UUID), connected=False)
        room_service = AsyncMock()
        room_service.get_room_snapshot.return_value = MagicMock(seats=[seat1, seat2, seat3])
        mock_get_room.return_value = room_service

        settings = MagicMock()
        settings.TURN_SKIP_GRACE_PERIOD = 0
        mock_get_settings.return_value = settings
        mock_asyncio.sleep = AsyncMock()

        auto_events, auto_played_ids = await _auto_play_disconnected_turns(
            "room-123", state, MagicMock()
        )

        # Both P2 and P3 were auto-played
        assert str(P2_UUID) in auto_played_ids
        assert str(P3_UUID) in auto_played_ids
        assert str(P1_UUID) not in auto_played_ids

        turn_started = [e for e in auto_events if e.get("event_type") == "turn_started"]
        assert len(turn_started) >= 2  # TurnStarted(P3) and TurnStarted(P1)

        for ts in turn_started:
            pid = ts["player_id"]
            if pid == str(P3_UUID):
                assert ts["auto_played"] is True, (
                    "TurnStarted for disconnected P3 should be auto_played"
                )
            elif pid == str(P1_UUID):
                assert ts["auto_played"] is not True, (
                    "TurnStarted for connected P1 should not be auto_played"
                )
