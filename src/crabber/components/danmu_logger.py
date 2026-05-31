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

            # skip self danmaku
            if uid == ctx.cred_manager.uid:
                logger.debug(f"skip self danmaku from user {uid}")
                return

            # skip low-effort/spam number danmaku
            if should_skip_danmu(msg):
                logger.debug(f"skip spam/number danmaku: {usr}说: {msg}")
                return

            logger.debug(f"{usr}说: {msg}")

            if ctx.db:
                await ctx.db.record_danmaku(
                    room_id=ctx.room_id,
                    user=usr,
                    uid=uid,
                    content=msg,
                    timestamp=datetime.now(),
                    mode=info[0][1], # 1: normal, 4: bottom, others TBD
                    color=info[0][3], # Decimal of color
                )

        else:
            logger.debug(f"unknown DANMU_MSG event:\n{jsonify(event)}")

    return handler


def should_skip_danmu(msg: str) -> bool:
    if not isinstance(msg, str): return False

    # If the message is purely numeric
    if msg.isdigit():
        # 1. Single digit 1-9
        if len(msg) == 1:
            return msg in "123456789"

        # 2. Repeating digits (e.g., 111, 222, 333)
        if len(set(msg)) == 1:
            return True

        # 3. Consecutive digit sequences of length >= 3 (e.g., 123, 234, 321, 4321)
        if len(msg) >= 3 and (msg in "0123456789" or msg in "9876543210"):
            return True

    return False
