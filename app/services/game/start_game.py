from uuid import UUID

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameSettings,
    GameState,
    Player,
    Token,
    TokenState,
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
        safe_spaces.append(pos + (2 * grid_length - 2))

    starting_positions = starting_positions[:num_players]

    return BoardSetup(
        squares_to_win=(9 * grid_length) + 1,
        squares_to_homestretch=8 * grid_length + 1,
        starting_positions=starting_positions,
        get_out_rolls=game_settings.get_out_rolls,
        safe_spaces=safe_spaces,
    )


def _create_initial_tokens(player_id: UUID) -> list[Token]:
    """Create initial tokens for a player."""
    return [
        Token(
            token_id=f"{player_id}_token_{i + 1}",
            state=TokenState.HELL,
            progress=0,
            in_stack=False,
        )
        for i in range(4)
    ]


def _initialize_players(game_settings: GameSettings, starting_positions: list[int]) -> list[Player]:
    """Initialize players with randomized turn order."""
    shuffled_attributes = list(game_settings.player_attributes)
    # random.shuffle(shuffled_attributes)

    players = []
    for index, player_attr in enumerate(shuffled_attributes):
        player = Player(
            player_id=player_attr.player_id,
            name=player_attr.name,
            color=player_attr.color,
            turn_order=index + 1,
            abs_starting_index=starting_positions[index],
            tokens=_create_initial_tokens(player_attr.player_id),
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
        stacks=None,
    )

    # def _get_current_game_state(self, state_type: GameState) -> dict[str, Any]:
    #     """Get the current game state for broadcasting."""
    #     token_states = []
    #     for player in self.players:
    #         for token in player.tokens:
    #             token_states.append(
    #                 {
    #                     "player_id": str(player.player_id),
    #                     "token_id": token.token_id,
    #                     "state": token.state.value
    #                     if hasattr(token.state, "value")
    #                     else token.state,
    #                     "progress": token.progress,
    #                     "track_position": (token.progress + player.abs_starting_index),
    #                     "in_stack": token.in_stack,
    #                 }
    #             )
    #     return {
    #         "state_type": state_type.value if hasattr(state_type, "value") else state_type,
    #         "current_phase": self.current_phase.value
    #         if hasattr(self.current_phase, "value")
    #         else self.current_phase,
    #         "tokens": token_states,
    #     }

    # def start_game(self):
    #     if self.current_phase != GamePhase.NOT_STARTED:
    #         raise ValueError("Game has already started or finished.")
    #     self.current_phase = GamePhase.IN_PROGRESS
    #     current_turn_index = 0

    #     while not self._is_game_finished():
    #         turn = self._create_new_turn(current_turn_index)
    #         self._process_turn(turn)
    #         current_turn_index = (current_turn_index + 1) % len(self.players)

    # def _is_game_finished(self):
    #     for player in self.players:
    #         all_tokens_in_heaven = all(token.state == TokenState.HEAVEN for token in player.tokens)
    #         if all_tokens_in_heaven:
    #             self.current_phase = GamePhase.FINISHED
    #             return True
    #     return False

    # def _create_new_turn(self, turn_index: int):
    #     player = self.players[turn_index]
    #     turn = Turn(
    #         player_id=player.player_id,
    #         initial_roll=True,
    #         rolls_to_allocate=[],
    #         current_turn_order=player.turn_order,
    #         extra_rolls=0,
    #     )
    #     return turn

    # def _process_turn(self, turn: Turn):
    #     # Placeholder for turn processing logic
    #     pass
