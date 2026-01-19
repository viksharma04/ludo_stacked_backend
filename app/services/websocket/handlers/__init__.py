"""WebSocket message handler registry and dispatcher."""

import logging
from collections.abc import Awaitable, Callable

from app.schemas.ws import MessageType

from .base import HandlerContext, HandlerResult

logger = logging.getLogger(__name__)

# Type alias for handler functions
HandlerFunc = Callable[[HandlerContext], Awaitable[HandlerResult]]

# Handler registry: maps MessageType to handler function
_handlers: dict[MessageType, HandlerFunc] = {}


def handler(message_type: MessageType) -> Callable[[HandlerFunc], HandlerFunc]:
    """Decorator to register a handler for a message type.

    Usage:
        @handler(MessageType.PING)
        async def handle_ping(ctx: HandlerContext) -> HandlerResult:
            ...
    """

    def decorator(func: HandlerFunc) -> HandlerFunc:
        if message_type in _handlers:
            logger.warning(
                "Overwriting existing handler for %s",
                message_type,
            )
        _handlers[message_type] = func
        logger.debug("Registered handler for %s: %s", message_type, func.__name__)
        return func

    return decorator


async def dispatch(ctx: HandlerContext) -> HandlerResult | None:
    """Dispatch a message to its registered handler.

    Args:
        ctx: The handler context containing connection info and message.

    Returns:
        HandlerResult from the handler, or None if no handler is registered.
    """
    handler_func = _handlers.get(ctx.message.type)
    if handler_func is None:
        logger.debug(
            "No handler registered for message type %s from connection %s",
            ctx.message.type,
            ctx.connection_id,
        )
        return None

    return await handler_func(ctx)


# Import handlers to trigger registration
from . import leave  # noqa: E402, F401
from . import ping  # noqa: E402, F401
from . import ready  # noqa: E402, F401

__all__ = [
    "HandlerContext",
    "HandlerResult",
    "dispatch",
    "handler",
]
