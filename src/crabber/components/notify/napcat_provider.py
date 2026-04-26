import asyncio

from logging import Logger

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.logging import logger as default_logger
from crabber.services import NapCatService


async def send_notify(ctx: Crabber, room: RoomInfo, config: dict = {}, logger: Logger = default_logger) -> None:
    s = ctx.services.get("napcat", None)

    if not s or not isinstance(s, NapCatService):
        logger.warning("napcat service not found")
        return

    napcat: NapCatService = s

    content = (
        f"[CQ:image,file={room.cover}]\n"
        f"{room.uname}正在直播：{room.title}\n"
        f"分区：{room.area}\n"
        f"https://live.bilibili.com/{room.id}"
    )

    groups = config.get("groups", [])
    users = config.get("users", [])

    await napcat.send_msg_concurrently(content, groups, users)

    ctx.logger.info(f"success to send notify to group {groups} and user {users}")
