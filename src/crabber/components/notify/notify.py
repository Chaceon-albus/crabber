import asyncio

from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo

from crabber.components.notify.ntfy_provider import send_notify as send_ntfy_notify


default_events = [] # no event needed for notify component


def get_handler(ctx: Crabber, channels: list[dict], *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    async def handler(event: dict) -> None:
        # no handler needed for notify component
        pass

    async def _on_room_online(room_info: RoomInfo) -> None:
        logger.info(f"room {room_info.id} is online, sending notifications to channels...")
        for channel in channels:
            try:
                match provider := channel.get("provider", ""):
                    case "ntfy":
                        await send_ntfy_notify(room_info, channel.get("config", {}), logger)
                    case _:
                        logger.warning(f"unknown notify provider: {provider}")
            except Exception as e:
                logger.exception(f"channel {channel.get('name', '[notset]')} failed: {e}")


    ctx.add_online_callback(_on_room_online)


    return handler
