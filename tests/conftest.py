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
    Token,
    TokenState,
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
        squares_to_win=57,  # 52 road + 5 homestretch
        squares_to_homestretch=52,
        starting_positions=[0, 13, 26, 39],  # Every 13 squares
        safe_spaces=[0, 13, 26, 39, 8, 21, 34, 47],  # Starting positions + extra safe
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


def create_token(
    token_id: str, state: TokenState, progress: int = 0, in_stack: bool = False
) -> Token:
    """Helper to create a token."""
    return Token(
        token_id=token_id,
        state=state,
        progress=progress,
        in_stack=in_stack,
    )


def create_tokens_in_hell(player_id: UUID, count: int = 4) -> list[Token]:
    """Create tokens all in HELL state."""
    return [create_token(f"{player_id}_token_{i}", TokenState.HELL, 0) for i in range(1, count + 1)]


def create_player(
    player_id: UUID,
    name: str,
    color: str,
    turn_order: int,
    abs_starting_index: int,
    tokens: list[Token] | None = None,
    stacks: list[Stack] | None = None,
) -> Player:
    """Helper to create a player."""
    if tokens is None:
        tokens = create_tokens_in_hell(player_id)
    return Player(
        player_id=player_id,
        name=name,
        color=color,
        turn_order=turn_order,
        abs_starting_index=abs_starting_index,
        tokens=tokens,
        stacks=stacks,
    )


@pytest.fixture
def player1(standard_board_setup: BoardSetup) -> Player:
    """Player 1 with all tokens in HELL."""
    return create_player(
        player_id=PLAYER_1_ID,
        name="Player 1",
        color="red",
        turn_order=1,
        abs_starting_index=0,
    )


@pytest.fixture
def player2(standard_board_setup: BoardSetup) -> Player:
    """Player 2 with all tokens in HELL."""
    return create_player(
        player_id=PLAYER_2_ID,
        name="Player 2",
        color="blue",
        turn_order=2,
        abs_starting_index=13,
    )


@pytest.fixture
def player3(standard_board_setup: BoardSetup) -> Player:
    """Player 3 with all tokens in HELL."""
    return create_player(
        player_id=PLAYER_3_ID,
        name="Player 3",
        color="green",
        turn_order=3,
        abs_starting_index=26,
    )


@pytest.fixture
def player4(standard_board_setup: BoardSetup) -> Player:
    """Player 4 with all tokens in HELL."""
    return create_player(
        player_id=PLAYER_4_ID,
        name="Player 4",
        color="yellow",
        turn_order=4,
        abs_starting_index=39,
    )


@pytest.fixture
def two_player_game_not_started(
    player1: Player, player2: Player, two_player_board_setup: BoardSetup
) -> GameState:
    """Two-player game in NOT_STARTED phase."""
    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=[player1, player2],
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=two_player_board_setup,
        current_turn=None,
    )


@pytest.fixture
def four_player_game_not_started(
    player1: Player,
    player2: Player,
    player3: Player,
    player4: Player,
    standard_board_setup: BoardSetup,
) -> GameState:
    """Four-player game in NOT_STARTED phase."""
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
    """Game in progress with player 1's turn to roll."""
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
def game_with_token_on_road(player2: Player, two_player_board_setup: BoardSetup) -> GameState:
    """Game where player 1 has a token on the road at position 10."""
    # Player 1 with one token on road
    player1_tokens = [
        create_token(f"{PLAYER_1_ID}_token_1", TokenState.ROAD, 10),
        create_token(f"{PLAYER_1_ID}_token_2", TokenState.HELL, 0),
        create_token(f"{PLAYER_1_ID}_token_3", TokenState.HELL, 0),
        create_token(f"{PLAYER_1_ID}_token_4", TokenState.HELL, 0),
    ]
    player1 = create_player(
        player_id=PLAYER_1_ID,
        name="Player 1",
        color="red",
        turn_order=1,
        abs_starting_index=0,
        tokens=player1_tokens,
    )

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
