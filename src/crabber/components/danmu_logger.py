from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.misc import jsonify


default_events = ["DANMU_MSG"]


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    async def handler(event: dict) -> None:
        info = event.get("data", {}).get("info", {})

        if len(info) > 2 and len(info[2]) > 1:
            msg = info[1]
            usr = info[2][1]
            logger.info(f"{usr}说: {msg}")
        else:
            logger.debug(f"unknown DANMU_MSG event:\n{jsonify(event)}")

    return handler