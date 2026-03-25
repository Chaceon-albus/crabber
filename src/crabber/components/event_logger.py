from typing import Callable, Awaitable
from crabber.logging import logger
from crabber.misc import jsonify


default_events = ["ALL"]


def get_handler(*args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    async def handler(event: dict) -> None:
        logger.debug(f"Event received:\n{jsonify(event)}")

    return handler