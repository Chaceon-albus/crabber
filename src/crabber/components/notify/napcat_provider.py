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

    try:

        group_tasks = [napcat.send_msg(
            message_type="group",
            group_id=f"{gid}",
            message=content,
        ) for gid in config.get("groups", [])]

        private_tasks = [napcat.send_msg(
            message_type="private",
            user_id=f"{uid}",
            message=content,
        ) for uid in config.get("users", [])]

        results = await asyncio.gather(*group_tasks, *private_tasks, return_exceptions=True)
        all_ids = config.get("groups", []) + config.get("users", [])

        for k, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"failed to notify {all_ids[k]}: {res}")

    except Exception as e:
        logger.error(f"failed to send live notify msg: {e}")
    else:
        logger.info(f"success to broadcast live notify msg to {all_ids}")
        logger.debug(f"message = {content}")
