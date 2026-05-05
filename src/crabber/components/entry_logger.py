from typing import Callable, Awaitable

from crabber.crabber import Crabber


default_events = ["ENTRY_EFFECT", "ENTRY_EFFECT_MUST_RECEIVE"]


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    logger.warning("entry_logger is not finished")

    async def handler(event: dict) -> None:
        data: dict = event.get("data", {}).get("data", {})
        if not data: return

        # data.get("id", -1) # no idea
        data.get("uid", -1)
        data.get("is_mystery", False)
        data.get("priority", 100) # ?higher value means lower priority?
        data.get("uinfo", {}).get("base", {}).get("name")
        data.get("uinfo", {}).get("guard", {}).get("level")


    return handler