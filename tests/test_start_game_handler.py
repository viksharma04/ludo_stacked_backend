"""Tests for start_game WebSocket handler."""

import pytest

from app.services.room.service import RoomSnapshotData, SeatData
from app.services.websocket.handlers.start_game import (
    SEAT_COLORS,
    _build_game_settings_from_room,
)


class TestBuildGameSettingsFromRoom:
    """Tests for _build_game_settings_from_room helper function."""

    def test_builds_settings_for_two_players(self) -> None:
        """Should create game settings with two players from occupied seats."""
        room_snapshot = RoomSnapshotData(
            room_id="room-123",
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0,
                    user_id="00000000-0000-0000-0000-000000000001",
                    display_name="Alice",
                    ready="ready",
                    connected=True,
                    is_host=True,
                ),
                SeatData(
                    seat_index=1,
                    user_id="00000000-0000-0000-0000-000000000002",
                    display_name="Bob",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
                SeatData(seat_index=2),  # Empty seat
                SeatData(seat_index=3),  # Empty seat
            ],
            version=1,
        )

        settings = _build_game_settings_from_room(room_snapshot)

        assert settings.num_players == 2
        assert len(settings.player_attributes) == 2
        assert settings.grid_length == 6
        assert settings.get_out_rolls == [6]

        # Check player attributes
        assert str(settings.player_attributes[0].player_id) == "00000000-0000-0000-0000-000000000001"
        assert settings.player_attributes[0].name == "Alice"
        assert settings.player_attributes[0].color == "red"

        assert str(settings.player_attributes[1].player_id) == "00000000-0000-0000-0000-000000000002"
        assert settings.player_attributes[1].name == "Bob"
        assert settings.player_attributes[1].color == "blue"

    def test_builds_settings_for_four_players(self) -> None:
        """Should create game settings with four players."""
        room_snapshot = RoomSnapshotData(
            room_id="room-123",
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0,
                    user_id="00000000-0000-0000-0000-000000000001",
                    display_name="Alice",
                    ready="ready",
                    connected=True,
                    is_host=True,
                ),
                SeatData(
                    seat_index=1,
                    user_id="00000000-0000-0000-0000-000000000002",
                    display_name="Bob",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
                SeatData(
                    seat_index=2,
                    user_id="00000000-0000-0000-0000-000000000003",
                    display_name="Charlie",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
                SeatData(
                    seat_index=3,
                    user_id="00000000-0000-0000-0000-000000000004",
                    display_name="Diana",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
            ],
            version=1,
        )

        settings = _build_game_settings_from_room(room_snapshot)

        assert settings.num_players == 4
        assert len(settings.player_attributes) == 4

        # Check all colors are assigned correctly by seat index
        assert settings.player_attributes[0].color == "red"  # seat 0
        assert settings.player_attributes[1].color == "blue"  # seat 1
        assert settings.player_attributes[2].color == "green"  # seat 2
        assert settings.player_attributes[3].color == "yellow"  # seat 3

    def test_uses_fallback_display_name_when_missing(self) -> None:
        """Should use fallback name when display_name is None."""
        room_snapshot = RoomSnapshotData(
            room_id="room-123",
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0,
                    user_id="00000000-0000-0000-0000-000000000001",
                    display_name=None,  # Missing display name
                    ready="ready",
                    connected=True,
                    is_host=True,
                ),
                SeatData(
                    seat_index=1,
                    user_id="00000000-0000-0000-0000-000000000002",
                    display_name="Bob",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
                SeatData(seat_index=2),
                SeatData(seat_index=3),
            ],
            version=1,
        )

        settings = _build_game_settings_from_room(room_snapshot)

        assert settings.player_attributes[0].name == "Player 1"  # Fallback
        assert settings.player_attributes[1].name == "Bob"

    def test_raises_error_with_single_player(self) -> None:
        """Should raise ValueError with fewer than 2 players."""
        room_snapshot = RoomSnapshotData(
            room_id="room-123",
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0,
                    user_id="00000000-0000-0000-0000-000000000001",
                    display_name="Alice",
                    ready="ready",
                    connected=True,
                    is_host=True,
                ),
                SeatData(seat_index=1),  # Empty
                SeatData(seat_index=2),  # Empty
                SeatData(seat_index=3),  # Empty
            ],
            version=1,
        )

        with pytest.raises(ValueError, match="At least 2 players are required"):
            _build_game_settings_from_room(room_snapshot)

    def test_raises_error_with_no_players(self) -> None:
        """Should raise ValueError with no players."""
        room_snapshot = RoomSnapshotData(
            room_id="room-123",
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(seat_index=0),  # Empty
                SeatData(seat_index=1),  # Empty
                SeatData(seat_index=2),  # Empty
                SeatData(seat_index=3),  # Empty
            ],
            version=1,
        )

        with pytest.raises(ValueError, match="At least 2 players are required"):
            _build_game_settings_from_room(room_snapshot)

    def test_players_in_non_consecutive_seats(self) -> None:
        """Should handle players in non-consecutive seats correctly."""
        room_snapshot = RoomSnapshotData(
            room_id="room-123",
            code="ABC123",
            status="ready_to_start",
            visibility="private",
            ruleset_id="classic",
            max_players=4,
            seats=[
                SeatData(
                    seat_index=0,
                    user_id="00000000-0000-0000-0000-000000000001",
                    display_name="Alice",
                    ready="ready",
                    connected=True,
                    is_host=True,
                ),
                SeatData(seat_index=1),  # Empty
                SeatData(seat_index=2),  # Empty
                SeatData(
                    seat_index=3,
                    user_id="00000000-0000-0000-0000-000000000004",
                    display_name="Diana",
                    ready="ready",
                    connected=True,
                    is_host=False,
                ),
            ],
            version=1,
        )

        settings = _build_game_settings_from_room(room_snapshot)

        assert settings.num_players == 2
        # Colors should match their seat indices
        assert settings.player_attributes[0].color == "red"  # seat 0
        assert settings.player_attributes[1].color == "yellow"  # seat 3


class TestSeatColors:
    """Tests for SEAT_COLORS constant."""

    def test_has_four_colors(self) -> None:
        """Should have exactly 4 standard Ludo colors."""
        assert len(SEAT_COLORS) == 4

    def test_standard_ludo_colors(self) -> None:
        """Should have the standard Ludo color set."""
        assert SEAT_COLORS == ["red", "blue", "green", "yellow"]
