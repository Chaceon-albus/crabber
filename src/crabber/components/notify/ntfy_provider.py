import aiohttp

from logging import Logger

from crabber.room_info import RoomInfo
from crabber.logging import logger as default_logger


async def send_notify(room: RoomInfo, config: dict = {}, logger: Logger = default_logger) -> None:

    name = config.get("name", "[notset]")
    endpoint = config.get("endpoint", "")
    topic = config.get("topic", "")
    token = config.get("token", "")
    priority = config.get("priority", 3)
    replace_map = config.get("replace_host", {})


    if not endpoint:
        logger.warning(f"ntfy[{name}] endpoint not configured, skipping notify")
        return

    if not topic:
        logger.warning(f"ntfy[{name}] topic not configured, skipping notify")
        return


    headers = {"Authorization": f"Bearer {token}"} if token else {}
    payload = {
        "priority": priority,
        "topic": topic,
        "title": f"{room.uname}正在直播：{room.title}",
        "message": room.area,
        "attach": replace_host(room.cover, replace_map),
        # "click": f"https://live.bilibili.com/{room.id}", # be not too aggressive
        "actions": [
            {
                "action": "view",
                "label": "让我康康",
                "url": f"https://live.bilibili.com/{room.id}",
                "clear": True
            }
        ],
    }

    async with aiohttp.ClientSession() as client:
        try:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"ntfy[{name}] failed to send notification: {e}")


def replace_host(url: str, replace_map: dict) -> str:
    for old_host, new_host in replace_map.items():
        url = url.replace(old_host, new_host)

    return url
