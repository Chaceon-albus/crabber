from typing import Callable, Awaitable
from datetime import datetime

from crabber.crabber import Crabber
from crabber.misc import jsonify


default_events = ["DANMU_MSG"]


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    async def handler(event: dict) -> None:
        info = event.get("data", {}).get("info", {})

        if len(info) > 2 and len(info[2]) > 1:
            msg = info[1]
            uid = info[2][0]
            usr = info[2][1]
            logger.debug(f"{usr}说: {msg}")

            if ctx.db:
                await ctx.db.record_danmaku(
                    room_id=ctx.room_id,
                    user=usr,
                    uid=uid,
                    content=msg,
                    timestamp=datetime.now()
                )

        else:
            logger.debug(f"unknown DANMU_MSG event:\n{jsonify(event)}")

    return handler