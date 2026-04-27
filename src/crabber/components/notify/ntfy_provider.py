from logging import Logger

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.logging import logger as default_logger
from crabber.services import NtfyService


# let it crash if anything goes wrong, caller will handle it
async def send_notify(ctx: Crabber, room: RoomInfo, config: dict = {}, logger: Logger = default_logger) -> None:

    s = ctx.services.get("ntfy", None)

    if not s or not isinstance(s, NtfyService):
        logger.warning("ntfy service not found")
        return

    ntfy: NtfyService = s

    name = config.get("name", "[notset]")
    topic = config.get("topic", "")
    priority = config.get("priority", 3)
    replace_map = config.get("replace_host", {})

    if not topic:
        logger.warning(f"ntfy[{name}] topic not configured, skipping notify")
        return

    title = f"{room.uname}正在直播：{room.title}"
    message = room.area
    attach = replace_host(room.cover, replace_map)
    actions = [
        {
            "action": "view",
            "label": "让我康康",
            "url": f"https://live.bilibili.com/{room.id}",
            "clear": True
        }
    ]

    await ntfy.send_notify(
        topic=topic,
        title=title,
        message=message,
        priority=priority,
        attach=attach,
        actions=actions
    )

    ctx.logger.info(f"success to send notify to ntfy topic {topic}")


def replace_host(url: str, replace_map: dict) -> str:
    for old_host, new_host in replace_map.items():
        url = url.replace(old_host, new_host)

    return url
