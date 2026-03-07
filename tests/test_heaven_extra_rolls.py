"""Tests for extra rolls granted when a stack reaches heaven.

Rule: When a stack reaches heaven, the player is granted extra rolls
equal to the stack's height (1 per piece in the stack).
"""

from app.schemas.game_engine import (
    BoardSetup,
    CurrentEvent,
    GamePhase,
    GameState,
    Stack,
    StackState,
    Turn,
)
from app.services.game.engine.actions import MoveAction, RollAction
from app.services.game.engine.events import (
    GameEnded,
    RollGranted,
)
from app.services.game.engine.movement import apply_split_move, apply_stack_move
from app.services.game.engine.process import process_action

from .conftest import (
    PLAYER_1_ID,
    PLAYER_2_ID,
    create_player,
    create_stack,
    create_stacks_in_hell,
)


def _make_two_player_state(
    player1_stacks: list[Stack],
    board_setup: BoardSetup,
    player2_stacks: list[Stack] | None = None,
    current_event: CurrentEvent = CurrentEvent.PLAYER_ROLL,
    extra_rolls: int = 0,
) -> GameState:
    """Build a minimal two-player IN_PROGRESS state with player 1's turn."""
    player1 = create_player(
        player_id=PLAYER_1_ID,
        name="Player 1",
        color="red",
        turn_order=1,
        abs_starting_index=0,
        stacks=player1_stacks,
    )
    player2 = create_player(
        player_id=PLAYER_2_ID,
        name="Player 2",
        color="blue",
        turn_order=2,
        abs_starting_index=26,
        stacks=player2_stacks if player2_stacks is not None else create_stacks_in_hell(),
    )
    turn = Turn(
        player_id=PLAYER_1_ID,
        initial_roll=True,
        rolls_to_allocate=[],
        legal_moves=[],
        current_turn_order=1,
        extra_rolls=extra_rolls,
    )
    return GameState(
        phase=GamePhase.IN_PROGRESS,
        players=[player1, player2],
        current_event=current_event,
        board_setup=board_setup,
        current_turn=turn,
    )


class TestHeavenGrantsExtraRolls:
    """Reaching heaven should grant extra rolls equal to stack height."""

    def test_height_1_stack_grants_1_extra_roll(self, standard_board_setup: BoardSetup):
        """A height-1 stack reaching heaven should increment extra_rolls by 1."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1",
            roll=3,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        assert result.state.current_turn.heaven_extra_rolls == 1

    def test_height_3_stack_grants_3_extra_rolls(self, standard_board_setup: BoardSetup):
        """A height-3 stack reaching heaven should increment extra_rolls by 3."""
        player1_stacks = [
            create_stack("stack_1_2_3", StackState.HOMESTRETCH, 3, 54),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        # Roll 3: effective = 3/3 = 1, progress 54+1 = 55 = heaven
        result = apply_stack_move(
            state=state,
            stack_id="stack_1_2_3",
            roll=3,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        assert result.state.current_turn.heaven_extra_rolls == 3

    def test_split_move_grants_extra_rolls_for_moving_height(
        self, standard_board_setup: BoardSetup
    ):
        """When a split move reaches heaven, extra rolls = moving piece height."""
        parent = create_stack("stack_1_2", StackState.HOMESTRETCH, 2, 53)
        player1_stacks = [
            parent,
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        # Split: stack_1 (height 1) moves with roll=2, effective=2/1=2, 53+2=55=heaven
        result = apply_split_move(
            state=state,
            parent=parent,
            remaining_id="stack_2",
            moving_id="stack_1",
            roll=2,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        # Moving piece has height 1, so 1 extra roll
        assert result.state.current_turn.heaven_extra_rolls == 1

    def test_heaven_extra_rolls_add_to_existing(self, standard_board_setup: BoardSetup):
        """Extra rolls from heaven should add to any existing extra_rolls."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.HELL, 1, 0),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        # Start with 2 extra rolls already queued
        state = _make_two_player_state(player1_stacks, standard_board_setup, extra_rolls=2)
        player = next(p for p in state.players if p.player_id == PLAYER_1_ID)

        result = apply_stack_move(
            state=state,
            stack_id="stack_1",
            roll=3,
            player=player,
            board_setup=standard_board_setup,
        )

        assert result.success
        assert result.state.current_turn.heaven_extra_rolls == 1  # heaven adds to its own counter
        assert result.state.current_turn.extra_rolls == 2  # capture rolls unchanged


class TestHeavenExtraRollFullFlow:
    """Test the full turn flow with heaven extra rolls."""

    def test_heaven_extra_roll_allows_another_roll(self, standard_board_setup: BoardSetup):
        """After reaching heaven, the player should get to roll again."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.ROAD, 1, 10),
            create_stack("stack_3", StackState.HELL, 1, 0),
            create_stack("stack_4", StackState.HELL, 1, 0),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        # Roll 3
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move stack_1 to heaven (52+3=55)
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Should be in PLAYER_ROLL state (extra roll granted)
        assert state.current_event == CurrentEvent.PLAYER_ROLL
        # Still player 1's turn
        assert state.current_turn.player_id == PLAYER_1_ID

        # A RollGranted event should have been emitted
        roll_granted = [e for e in result.events if isinstance(e, RollGranted)]
        assert len(roll_granted) >= 1
        heaven_grants = [e for e in roll_granted if e.reason == "reached_heaven"]
        assert len(heaven_grants) == 1

    def test_game_ending_heaven_does_not_grant_usable_roll(
        self, standard_board_setup: BoardSetup
    ):
        """When the last stack reaches heaven (game over), no extra roll is used."""
        player1_stacks = [
            create_stack("stack_1", StackState.HOMESTRETCH, 1, 52),
            create_stack("stack_2", StackState.HEAVEN, 1, 55),
            create_stack("stack_3", StackState.HEAVEN, 1, 55),
            create_stack("stack_4", StackState.HEAVEN, 1, 55),
        ]
        state = _make_two_player_state(player1_stacks, standard_board_setup)

        # Roll 3
        result = process_action(state, RollAction(value=3), PLAYER_1_ID)
        assert result.success
        state = result.state

        # Move last stack to heaven
        result = process_action(state, MoveAction(stack_id="stack_1", roll_value=3), PLAYER_1_ID)
        assert result.success

        # Game should end
        assert result.state.phase == GamePhase.FINISHED
        game_ended = next((e for e in result.events if isinstance(e, GameEnded)), None)
        assert game_ended is not None
        assert game_ended.winner_id == PLAYER_1_ID
