import asyncio

from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.misc import coin_to_cny, format_timedelta


default_events = ["SEND_GIFT", "USER_TOAST_MSG", "SUPER_CHAT_MESSAGE"]


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    is_online = False

    gift_revenue = 0.0
    guard_revenue = 0.0
    sc_revenue = 0.0


    async def handler(event: dict) -> None:
        cmd = event.get("data", {}).get("cmd", "unknown")
        data = event.get("data", {}).get("data", {})
        value_in_cny = 0.0

        nonlocal gift_revenue, guard_revenue, sc_revenue

        match cmd:

            case "SEND_GIFT":
                uname = data.get("uname", "[unknown]")
                user = data.get("sender_uinfo", {}).get("base", {}).get("name", uname)

                action = data.get("action", "投喂")
                gift_name = data.get("giftName", "[unknown]")
                num = data.get("num", 1)
                price = data.get("price", 0)

                coin = data.get("total_coin", price * num)
                value_in_cny = coin_to_cny(coin)

                gift_revenue += value_in_cny
                logger.info(f"{user} {action}了 {gift_name}×{num}，价值￥{value_in_cny:.2f}")

            case "USER_TOAST_MSG":
                num  = data.get("num", 1)
                unit = data.get("unit", "月")
                role = data.get("role_name", "舰长")
                user = data.get("username", "[unknown]")
                price = data.get("price", 0) # this is total price, not unit price
                value_in_cny = coin_to_cny(price)

                guard_revenue += value_in_cny
                logger.info(f"{user} 开通了{num}个{unit}的{role}，价值￥{value_in_cny:.2f}")

            case "SUPER_CHAT_MESSAGE":
                user = data.get("user_info", {}).get("uname", "[unknown]")
                message = data.get("message", "")
                value_in_cny = data.get("price", 0) # CNY price

                sc_revenue += value_in_cny
                logger.info(f"{user} 发送了￥{value_in_cny:.2f}的醒目留言: {message}")

            case _:
                logger.warning(f"received unsupported event: {cmd}")


    def _clear_records() -> None:
        nonlocal gift_revenue, guard_revenue, sc_revenue
        gift_revenue = 0.0
        guard_revenue = 0.0
        sc_revenue = 0.0


    async def _on_room_online(info: RoomInfo) -> None:
        # this.start_time - previous.end_time
        dura = info.start_time - info.end_time
        logger.info(f"距离上次直播结束经过了{format_timedelta(dura)}")

        if sum_str := summary(gift_revenue, guard_revenue, sc_revenue):
            logger.info(sum_str)

        _clear_records() # clear records after status change

    async def _on_room_offline(info: RoomInfo) -> None:
        # this.end_time - this.start_time
        dura = info.end_time - info.start_time
        logger.info(f"本次直播时长为{format_timedelta(dura)}")

        if sum_str := summary(gift_revenue, guard_revenue, sc_revenue):
            logger.info(sum_str)

        _clear_records() # clear records after status change

    async def _on_task_cancel(info: RoomInfo) -> None:
        if sum_str := summary(gift_revenue, guard_revenue, sc_revenue):
            logger.info(f"未提交的记录：{sum_str}, start={info.start_time}, end={info.end_time}")


    async def _watch_live_status() -> None:
        try:

            while True:

                try:
                    nonlocal is_online
                    if ctx.room_info.is_online != is_online:

                        is_online = ctx.room_info.is_online

                        if is_online:
                            await _on_room_online(ctx.room_info)
                        else:
                            await _on_room_offline(ctx.room_info)

                except Exception as e:
                    logger.exception(e)

                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.debug(f"received cancel signal")
            await _on_task_cancel(ctx.room_info)
            raise


    ctx.add_task(_watch_live_status())


    return handler


def summary(gift: float, guard: float, sc: float) -> str:
    return f"收到礼物￥{gift:.2f}，大航海￥{guard:.2f}，SC￥{sc:.2f}，共￥{gift + guard + sc:.2f}" if gift + guard + sc > 0 else ""