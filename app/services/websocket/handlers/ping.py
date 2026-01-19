"""Handler for PING messages."""

import logging

from app.schemas.ws import MessageType, PongPayload, WSServerMessage

from . import handler
from .base import HandlerContext, HandlerResult

logger = logging.getLogger(__name__)


@handler(MessageType.PING)
async def handle_ping(ctx: HandlerContext) -> HandlerResult:
    """Handle PING message by updating heartbeat and responding with PONG."""
    await ctx.manager.heartbeat(ctx.connection_id)

    logger.debug("Ping/pong for connection %s", ctx.connection_id)

    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.PONG,
            request_id=ctx.message.request_id,
            payload=PongPayload().model_dump(),
        ),
    )
