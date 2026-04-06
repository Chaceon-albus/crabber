from datetime import datetime, timedelta
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

    async def _on_room_online(room_info: RoomInfo, misfire_grace_time: float = 60.0) -> None:
        if room_info.start_time is not None:
            if datetime.now() - room_info.start_time > timedelta(seconds=misfire_grace_time):
                logger.info(f"room {room_info.id} has been online for more than {misfire_grace_time} seconds, skip...")
                return

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


    _on_room_online.__name__ = "[notify]_online"
    ctx.add_online_callback(_on_room_online)


    return handler
