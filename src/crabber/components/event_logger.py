from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.misc import jsonify


default_events = ["ALL"]


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    logger.info("event logger output in debug level by default")

    async def handler(event: dict) -> None:
        logger.debug(f"event received:\n{jsonify(event)}")

    return handler