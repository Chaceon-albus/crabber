from logging import Logger

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.logging import logger as default_logger
from crabber.misc import ensure_bili_url, resize_bili_image
from crabber.qq_send import send_qq_message
from crabber.rich_message import Block, Heading, Image, LinkButton, Paragraph, RichMessage, Text


# 16:9, also keeps the image small so the platform transfers it quickly
COVER_WIDTH, COVER_HEIGHT = 640, 360


# let it crash if anything goes wrong, caller will handle it
async def send_notify(
    ctx: Crabber,
    room: RoomInfo,
    config: dict | None = None,
    logger: Logger = default_logger,
) -> None:

    config = config or {}

    groups = config.get("groups", [])
    users = config.get("users", [])

    if not room.cover:
        logger.warning(f"cover url not found in {room}")

    await send_qq_message(ctx, build_live_message(room), groups, users)

    logger.info(f"sent notify to group {groups} and user {users}")


def build_live_message(room: RoomInfo) -> RichMessage:

    blocks: list[Block] = [Heading(f"{room.uname} 正在直播", level=2)]

    if room.cover:
        if (cover := resize_bili_image(room.cover, COVER_WIDTH, COVER_HEIGHT)):
            image = Image(cover, COVER_WIDTH, COVER_HEIGHT, alt="直播封面")
        else:
            image = Image(ensure_bili_url(room.cover), alt="直播封面")
        blocks.append(Paragraph([image]))

    blocks.append(Paragraph([
        Text(room.title, bold=True),
        Text(f"\n分区：{room.area}"),
    ]))

    return RichMessage(
        blocks=blocks,
        buttons=[LinkButton("打开直播间", f"https://live.bilibili.com/{room.id}")],
    )
