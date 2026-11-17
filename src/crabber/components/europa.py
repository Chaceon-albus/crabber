from typing import Callable, Awaitable

from bilibili_api import Danmaku

from crabber.crabber import Crabber
from crabber.components import empty_handler
from crabber.misc import jsonify
from crabber.qq_send import send_qq_message
from crabber.rich_message import Heading, Paragraph, RichMessage, Text


default_events = []


def get_handler(
    ctx: Crabber,
    participate: bool = False,
    groups: list[int] | None = None, users: list[int] | None = None,
    *args, **kwargs,
) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger
    groups = groups or []
    users  = users or []
    anchor_record: dict[int, str] = {}


    async def _send_notification(message: RichMessage) -> None:
        try:
            await send_qq_message(ctx, message, groups, users)
        except Exception as e:
            logger.error(f"failed to send award results: {e}")


    async def on_lot_start(event: dict) -> None:
        logger.debug(f"天选时刻开始事件：\n{jsonify(event)}")

        try:
            data: dict = event.get("data", {}).get("data", {})

            if (lot_id := data.get("id", -1)) < 0: return
            danmu = data.get("danmu", "[EMPTY]")

            if danmu and danmu != "[EMPTY]" and participate and ctx.room and ctx.has_credential:
                # idk how to participate, try to send a danmaku
                ctx.add_task(ctx.room.send_danmaku(
                    danmaku=Danmaku(danmu),
                    room_id=ctx.room_id,
                ))

            anchor_record[lot_id] = danmu
        except Exception as e:
            logger.error(f"failed to get anchor info: {e}")


    async def on_lot_award(event: dict) -> None:
        logger.debug(f"天选时刻中奖事件：\n{jsonify(event)}")

        try:
            data: dict = event.get("data", {}).get("data", {})

            if (lot_id := data.get("id", -1)) < 0:
                logger.info(f"ANCHOR_LOT_AWARD event got no id:\n{jsonify(event)}")
                return

            winners = data.get("award_users", [])
            award = data.get("award_name", "[UNKNOWN]")
            num   = data.get("award_num", 1)
            danmu = anchor_record.pop(lot_id, "[UNKNOWN]")

            winner_lines = [
                f"{user.get('uname', '[UNKNOWN]')} (uid: {user.get('uid', -1)})"
                for user in winners
            ]

            logger.info(f"天选时刻({lot_id})：发送“{danmu}”获得 {award}×{num}：{', '.join(winner_lines)}")
            await _send_notification(build_award_message(award, num, danmu, winner_lines))
        except Exception as e:
            logger.error(f"failed to get anchor award: {e}")


    ctx.add_handler("ANCHOR_LOT_START", on_lot_start)
    ctx.add_handler("ANCHOR_LOT_AWARD", on_lot_award)
    # ctx.add_handler("ANCHOR_LOT_END", empty_handler)
    # ctx.add_handler("ANCHOR_LOT_NOTICE", empty_handler)


    return empty_handler


def build_award_message(award: str, num: int, danmu: str, winner_lines: list[str]) -> RichMessage:
    return RichMessage(blocks=[
        Heading("天选时刻开奖"),
        Paragraph([
            Text("奖品："),
            Text(f"{award} × {num}", bold=True),
            Text(f"\n口令：“{danmu}”"),
        ]),
        Paragraph([
            Text("中奖用户：", bold=True),
            Text("\n" + "\n".join(winner_lines) if winner_lines else "\n无"),
        ]),
    ])
