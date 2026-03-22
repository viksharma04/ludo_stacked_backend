"""Handler for GAME_STATE request messages."""

import logging

from app.schemas.ws import (
    GameStatePayload,
    MessageType,
    WSServerMessage,
)
from app.services.game.state import get_game_state

from . import handler
from .base import (
    HandlerContext,
    HandlerResult,
    error_response,
    require_authenticated,
)

logger = logging.getLogger(__name__)


@handler(MessageType.GAME_STATE)
async def handle_game_state(ctx: HandlerContext) -> HandlerResult:
    """Handle GAME_STATE request — return full game state for reconnection sync.

    Client sends: { type: "game_state", request_id: "..." }
    Server sends: { type: "game_state", request_id: "...", payload: { game_state: {...} } }
    """
    auth_error = require_authenticated(ctx)
    if auth_error:
        return auth_error

    connection = ctx.manager.get_connection(ctx.connection_id)
    if connection is None or connection.room_id is None:
        return error_response(
            error_code="NOT_IN_ROOM",
            message="You are not in a room",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    game_state_dict = await get_game_state(connection.room_id)
    if game_state_dict is None:
        return error_response(
            error_code="GAME_NOT_FOUND",
            message="No game in progress for this room",
            error_type=MessageType.GAME_ERROR,
            request_id=ctx.message.request_id,
        )

    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.GAME_STATE,
            request_id=ctx.message.request_id,
            payload=GameStatePayload(
                game_state=game_state_dict,
            ).model_dump(),
        ),
    )
