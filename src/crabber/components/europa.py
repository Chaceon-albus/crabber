from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.services import NapCatService
from crabber.components import empty_handler
from crabber.misc import jsonify


default_events = []


def get_handler(ctx: Crabber, groups: list[int] | None = None, users: list[int] | None = None, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger
    groups = groups or []
    users  = users or []
    anchor_record: dict[int, str] = {}


    async def _send_notification(msg: str) -> None:
        if (napcat := ctx.get_service(NapCatService)) is None:
            return

        try:
            await napcat.send_msg_concurrently(msg, groups, users)
        except Exception as e:
            logger.error(f"failed to send award results: {e}")


    async def on_lot_start(event: dict) -> None:
        logger.debug(f"天选时刻开始事件：\n{jsonify(event)}")

        try:
            data: dict = event.get("data", {}).get("data", {})

            if (lot_id := data.get("id", -1)) < 0: return
            danmu = data.get("danmu", "[EMPTY]")

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

            users = data.get("award_users", [])
            award = data.get("award_name", "[UNKNOWN]")
            num   = data.get("award_num", 1)
            danmu = anchor_record.pop(lot_id, "[UNKNOWN]")

            if len(users) > 1:
                brief = f"下列用户在天选时刻({lot_id})中通过发送“{danmu}”获得了 {award}×{num}：\n"
            else:
                brief = f"天选时刻({lot_id})中发送“{danmu}”并获得 {award}×{num} 的幸运儿是："

            brief += "\n".join([
                f"{user.get('uname', '[UNKNOWN]')} (uid: {user.get('uid', -1)})"
                for user in users
            ])

            logger.info(brief)
            await _send_notification(brief)
        except Exception as e:
            logger.error(f"failed to get anchor award: {e}")


    ctx.add_handler("ANCHOR_LOT_START", on_lot_start)
    ctx.add_handler("ANCHOR_LOT_AWARD", on_lot_award)
    # ctx.add_handler("ANCHOR_LOT_END", empty_handler)
    # ctx.add_handler("ANCHOR_LOT_NOTICE", empty_handler)


    return empty_handler
