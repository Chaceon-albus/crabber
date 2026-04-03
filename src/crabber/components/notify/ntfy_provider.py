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
        "icon": "https://www.bilibili.com/favicon.ico",
        "title": f"正在直播：{room.title}",
        "message": room.area,
        "attach": room.cover,
        "click": f"https://live.bilibili.com/{room.id}",
        "actions": [
            {
                "action": "view",
                "label": "让我康康",
                "url": f"https://live.bilibili.com/{room.id}",
                "clear": True
            }
        ]
    }

    async with aiohttp.ClientSession() as client:
        try:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"ntfy[{name}] failed to send notification: {e}")
