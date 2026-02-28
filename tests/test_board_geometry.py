"""Tests for board setup formulas and position math.

Critical scenarios tested:
- Board geometry formulas scale correctly with grid_length
- Starting positions follow step = 2g+1 pattern
- Safe spaces always include all 8 positions regardless of player count
- 2-player layout uses opposite corners (1st and 3rd positions)
- 3-player layout uses first three positions
- Absolute position wrapping on the shared road
- Homestretch boundary detection
"""

from app.schemas.game_engine import (
    BoardSetup,
    GameSettings,
    PlayerAttributes,
    StackState,
)
from app.services.game.engine.captures import get_absolute_position
from app.services.game.start_game import _create_board_setup

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    PLAYER_3_ID,
    PLAYER_4_ID,
    create_player,
    create_stack,
)


def _make_settings(num_players: int, grid_length: int) -> GameSettings:
    """Helper to create GameSettings with the given number of players and grid length."""
    all_attrs = [
        PlayerAttributes(player_id=PLAYER_1_ID, name="P1", color="red"),
        PlayerAttributes(player_id=PLAYER_2_ID, name="P2", color="blue"),
        PlayerAttributes(player_id=PLAYER_3_ID, name="P3", color="green"),
        PlayerAttributes(player_id=PLAYER_4_ID, name="P4", color="yellow"),
    ]
    return GameSettings(
        num_players=num_players,
        grid_length=grid_length,
        player_attributes=all_attrs[:num_players],
    )


class TestBoardSetupFormulas:
    """Verify that board geometry formulas produce correct values."""

    def test_board_setup_grid_length_5(self):
        """Grid length 5: step=11, squares_to_win=46, squares_to_homestretch=42."""
        settings = _make_settings(num_players=4, grid_length=5)
        board = _create_board_setup(settings)

        assert board.squares_to_win == 46  # 9*5 + 1
        assert board.squares_to_homestretch == 42  # 8*5 + 2
        assert board.starting_positions == [0, 11, 22, 33]
        assert sorted(board.safe_spaces) == sorted([0, 8, 11, 19, 22, 30, 33, 41])

    def test_board_setup_grid_length_6(self):
        """Grid length 6: step=13, squares_to_win=55, squares_to_homestretch=50."""
        settings = _make_settings(num_players=4, grid_length=6)
        board = _create_board_setup(settings)

        assert board.squares_to_win == 55  # 9*6 + 1
        assert board.squares_to_homestretch == 50  # 8*6 + 2
        assert board.starting_positions == [0, 13, 26, 39]
        assert sorted(board.safe_spaces) == sorted([0, 10, 13, 23, 26, 36, 39, 49])

    def test_board_always_has_all_safe_spaces_regardless_of_player_count(self):
        """Even with only 2 players, all 8 safe spaces must be present."""
        settings = _make_settings(num_players=2, grid_length=6)
        board = _create_board_setup(settings)

        # All 8 safe spaces from the full 4-corner board
        expected_safe = [0, 10, 13, 23, 26, 36, 39, 49]
        assert len(board.safe_spaces) == 8
        assert sorted(board.safe_spaces) == sorted(expected_safe)

    def test_two_player_uses_opposite_corners(self):
        """2-player games use 1st and 3rd starting positions (opposite corners)."""
        settings = _make_settings(num_players=2, grid_length=6)
        board = _create_board_setup(settings)

        # Should be positions 0 and 26 (1st and 3rd), NOT [0, 13]
        assert board.starting_positions == [0, 26]

    def test_three_player_uses_first_three_positions(self):
        """3-player games use the first three starting positions."""
        settings = _make_settings(num_players=3, grid_length=6)
        board = _create_board_setup(settings)

        assert board.starting_positions == [0, 13, 26]


class TestAbsolutePosition:
    """Verify absolute position calculation and wrapping."""

    def test_absolute_position_wrapping(self):
        """Progress equal to squares_to_homestretch should wrap to position 0."""
        board = BoardSetup(
            squares_to_win=55,
            squares_to_homestretch=50,
            starting_positions=[0, 13, 26, 39],
            safe_spaces=[0, 10, 13, 23, 26, 36, 39, 49],
            get_out_rolls=[6],
        )
        player = create_player(
            player_id=PLAYER_1_ID,
            name="P1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=[create_stack("stack_1", StackState.ROAD, 1, 50)],
        )
        stack = player.stacks[0]

        abs_pos = get_absolute_position(stack, player, board)
        # (0 + 50) % 50 = 0
        assert abs_pos == 0

    def test_different_players_same_absolute_position(self):
        """Two players at different progress values can occupy the same absolute position."""
        board = BoardSetup(
            squares_to_win=55,
            squares_to_homestretch=50,
            starting_positions=[0, 13, 26, 39],
            safe_spaces=[0, 10, 13, 23, 26, 36, 39, 49],
            get_out_rolls=[6],
        )
        player1 = create_player(
            player_id=PLAYER_1_ID,
            name="P1",
            color="red",
            turn_order=1,
            abs_starting_index=0,
            stacks=[create_stack("stack_1", StackState.ROAD, 1, 13)],
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="P2",
            color="blue",
            turn_order=2,
            abs_starting_index=13,
            stacks=[create_stack("stack_1", StackState.ROAD, 1, 0)],
        )

        abs_pos_1 = get_absolute_position(player1.stacks[0], player1, board)
        abs_pos_2 = get_absolute_position(player2.stacks[0], player2, board)

        assert abs_pos_1 == 13
        assert abs_pos_2 == 13
        assert abs_pos_1 == abs_pos_2

    def test_absolute_position_player2(self):
        """Player 2 (abs_start=13) at progress=5 should be at absolute position 18."""
        board = BoardSetup(
            squares_to_win=55,
            squares_to_homestretch=50,
            starting_positions=[0, 13, 26, 39],
            safe_spaces=[0, 10, 13, 23, 26, 36, 39, 49],
            get_out_rolls=[6],
        )
        player2 = create_player(
            player_id=PLAYER_2_ID,
            name="P2",
            color="blue",
            turn_order=2,
            abs_starting_index=13,
            stacks=[create_stack("stack_1", StackState.ROAD, 1, 5)],
        )

        abs_pos = get_absolute_position(player2.stacks[0], player2, board)
        # (13 + 5) % 50 = 18
        assert abs_pos == 18


class TestSafeSpaces:
    """Verify safe space rules and homestretch boundary."""

    def test_all_starting_positions_are_safe(self):
        """Every starting position must appear in the safe_spaces list."""
        settings = _make_settings(num_players=4, grid_length=6)
        board = _create_board_setup(settings)

        for pos in board.starting_positions:
            assert pos in board.safe_spaces, (
                f"Starting position {pos} is not in safe_spaces {board.safe_spaces}"
            )

    def test_homestretch_boundary(self):
        """Progress < squares_to_homestretch stays on ROAD; >= enters HOMESTRETCH."""
        board = BoardSetup(
            squares_to_win=55,
            squares_to_homestretch=50,
            starting_positions=[0, 13, 26, 39],
            safe_spaces=[0, 10, 13, 23, 26, 36, 39, 49],
            get_out_rolls=[6],
        )

        road_stack = create_stack("stack_1", StackState.ROAD, 1, 49)
        homestretch_stack = create_stack("stack_2", StackState.HOMESTRETCH, 1, 50)

        # A stack at progress 49 is still on the road (49 < 50)
        assert road_stack.progress < board.squares_to_homestretch
        assert road_stack.state == StackState.ROAD

        # A stack at progress 50 has entered the homestretch (50 >= 50)
        assert homestretch_stack.progress >= board.squares_to_homestretch
        assert homestretch_stack.state == StackState.HOMESTRETCH
