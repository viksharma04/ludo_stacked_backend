from uuid import UUID

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameSettings,
    GameState,
    Player,
    Stack,
    StackState,
)


def validate_game_settings(game_settings: GameSettings) -> None:
    """Validate game settings before initializing a game."""
    if game_settings.num_players < 2:
        raise ValueError("A minimum of 2 players is required to start the game.")
    if game_settings.grid_length < 3:
        raise ValueError("Grid length must be at least 3.")
    if len(game_settings.player_attributes) != game_settings.num_players:
        raise ValueError("Number of player IDs must match the number of players.")

    # Ensure each player has unique id, name, and color
    player_ids: set[UUID] = set()
    player_names: set[str] = set()
    player_colors: set[str] = set()
    for player in game_settings.player_attributes:
        if player.player_id in player_ids:
            raise ValueError(f"Duplicate player ID found: {player.player_id}")
        if player.name in player_names:
            raise ValueError(f"Duplicate player name found: {player.name}")
        if player.color in player_colors:
            raise ValueError(f"Duplicate player color found: {player.color}")
        player_ids.add(player.player_id)
        player_names.add(player.name)
        player_colors.add(player.color)


def _create_board_setup(game_settings: GameSettings) -> BoardSetup:
    """Create board setup based on game settings."""
    grid_length = game_settings.grid_length
    num_players = game_settings.num_players

    starting_positions = [0] + [sum(2 * grid_length + 1 for _ in range(i + 1)) for i in range(3)]
    safe_spaces = []
    for pos in starting_positions:
        safe_spaces.append(pos)
        safe_spaces.append(pos + (2 * grid_length - 5))

    if num_players == 2:
        starting_positions = [starting_positions[0], starting_positions[2]]
    else:
        starting_positions = starting_positions[:num_players]

    return BoardSetup(
        grid_length=grid_length,
        loop_length=(8 * grid_length) + 4,
        squares_to_win=(9 * grid_length) + 1,
        squares_to_homestretch=8 * grid_length + 1,
        starting_positions=starting_positions,
        get_out_rolls=game_settings.get_out_rolls,
        safe_spaces=safe_spaces,
    )


def _create_initial_stacks() -> list[Stack]:
    """Create initial stacks for a player."""
    return [
        Stack(stack_id=f"stack_{i}", state=StackState.HELL, height=1, progress=0)
        for i in range(1, 5)
    ]


def _initialize_players(game_settings: GameSettings, starting_positions: list[int]) -> list[Player]:
    """Initialize players with deterministic turn order."""
    player_attributes = list(game_settings.player_attributes)

    players = []
    for index, player_attr in enumerate(player_attributes):
        player = Player(
            player_id=player_attr.player_id,
            name=player_attr.name,
            color=player_attr.color,
            turn_order=index + 1,
            abs_starting_index=starting_positions[index],
            stacks=_create_initial_stacks(),
        )
        players.append(player)

    return players


def initialize_game(game_settings: GameSettings) -> GameState:
    """
    Validate game settings and return an initialized GameState.

    Args:
        game_settings: The settings for the game including number of players,
                      player attributes, and grid length.

    Returns:
        An initialized GameState ready for the game to begin.

    Raises:
        ValueError: If game settings are invalid.
    """
    validate_game_settings(game_settings)

    board_setup = _create_board_setup(game_settings)
    players = _initialize_players(game_settings, board_setup.starting_positions)

    return GameState(
        phase=GamePhase.NOT_STARTED,
        players=players,
        current_event=CurrentEvent.PLAYER_ROLL,
        board_setup=board_setup,
        current_turn=None,
    )
