"""Shared fixtures for game engine tests."""

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

# Fixed UUIDs for deterministic testing
PLAYER_1_ID = UUID("00000000-0000-0000-0000-000000000001")
PLAYER_2_ID = UUID("00000000-0000-0000-0000-000000000002")
PLAYER_3_ID = UUID("00000000-0000-0000-0000-000000000003")
PLAYER_4_ID = UUID("00000000-0000-0000-0000-000000000004")


@pytest.fixture
def standard_board_setup() -> BoardSetup:
    """Standard 4-player board setup."""
    return BoardSetup(
        squares_to_win=57,
        squares_to_homestretch=52,
        starting_positions=[0, 13, 26, 39],
        safe_spaces=[0, 13, 26, 39, 8, 21, 34, 47],
        get_out_rolls=[6],
    )


@pytest.fixture
def two_player_board_setup() -> BoardSetup:
    """Two-player board setup."""
    return BoardSetup(
        squares_to_win=57,
        squares_to_homestretch=52,
        starting_positions=[0, 26],
        safe_spaces=[0, 26],
        get_out_rolls=[6],
    )


def create_stack(
    stack_id: str, state: StackState, height: int = 1, progress: int = 0
) -> Stack:
    """Helper to create a stack."""
    return Stack(stack_id=stack_id, state=state, height=height, progress=progress)


def create_stacks_in_hell(count: int = 4) -> list[Stack]:
    """Create stacks all in HELL state (stack_1 through stack_N)."""
    return [create_stack(f"stack_{i}", StackState.HELL, 1, 0) for i in range(1, count + 1)]


def create_player(
    player_id: UUID,
    name: str,
    color: str,
    turn_order: int,
    abs_starting_index: int,
    stacks: list[Stack] | None = None,
) -> Player:
    """Helper to create a player."""
    if stacks is None:
        stacks = create_stacks_in_hell()
    return Player(
        player_id=player_id,
        name=name,
        color=color,
        turn_order=turn_order,
        abs_starting_index=abs_starting_index,
        stacks=stacks,
    )


@pytest.fixture
def player1(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_1_ID, "Player 1", "red", 1, 0)


@pytest.fixture
def player2(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_2_ID, "Player 2", "blue", 2, 13)


@pytest.fixture
def player3(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_3_ID, "Player 3", "green", 3, 26)


@pytest.fixture
def player4(standard_board_setup: BoardSetup) -> Player:
    return create_player(PLAYER_4_ID, "Player 4", "yellow", 4, 39)


@pytest.fixture
def two_player_game_not_started(
    player1: Player, player2: Player, two_player_board_setup: BoardSetup
) -> GameState:
    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=[player1, player2],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=None,
    )


@pytest.fixture
def four_player_game_not_started(
    player1: Player, player2: Player, player3: Player, player4: Player,
    standard_board_setup: BoardSetup,
) -> GameState:
    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=[player1, player2, player3, player4],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=standard_board_setup,
        current_turn=None,
    )


@pytest.fixture
def game_player1_turn(
    player1: Player, player2: Player, two_player_board_setup: BoardSetup
) -> GameState:
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=True,
        rolls_to_allocate=[],
        legal_moves=[],
        current_turn_order=1,
        extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=turn,
    )


@pytest.fixture
def game_with_stack_on_road(player2: Player, two_player_board_setup: BoardSetup) -> GameState:
    """Game where player 1 has a stack on the road at progress 10."""
    player1 = create_player(
        player_id=PLAYER_1_ID, name="Player 1", color="red",
        turn_order=1, abs_starting_index=0,
        stacks=[
            create_stack("stack_1", StackState.ROAD, 1, 10),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ],
    )
    turn = Turn(
        player_id=PLAYER_1_ID, initial_roll=True,
        rolls_to_allocate=[], legal_moves=[],
        current_turn_order=1, extra_rolls=0,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=turn,
    )
