import asyncio

from datetime import datetime, timedelta
from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.misc import coin_to_cny, format_timedelta


default_events = ["SEND_GIFT", "USER_TOAST_MSG", "SUPER_CHAT_MESSAGE"]


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    is_online = False
    online_income = 0.0
    offline_income = 0.0

    async def handler(event: dict) -> None:
        cmd = event.get("data", {}).get("cmd", "unknown")
        data = event.get("data", {}).get("data", {})
        value_in_cny = 0.0

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

                logger.info(f"{user} {action}了 {gift_name}×{num}，价值￥{value_in_cny:.2f}")

            case "USER_TOAST_MSG":
                num  = data.get("num", 1)
                unit = data.get("unit", "月")
                role = data.get("role_name", "舰长")
                user = data.get("username", "[unknown]")
                price = data.get("price", 0) # this is total price, not unit price
                value_in_cny = coin_to_cny(price)
                logger.info(f"{user} 开通了{num}个{unit}的{role}，价值￥{value_in_cny:.2f}")

            case "SUPER_CHAT_MESSAGE":
                user = data.get("user_info", {}).get("uname", "[unknown]")
                message = data.get("message", "")
                value_in_cny = data.get("price", 0) # CNY price
                logger.info(f"{user} 发送了￥{value_in_cny:.2f}的醒目留言: {message}")

            case _:
                logger.warning(f"received unsupported event: {cmd}")


        if is_online:
            nonlocal online_income
            online_income += value_in_cny
        else:
            nonlocal offline_income
            offline_income += value_in_cny


    async def _on_room_online(dura: timedelta) -> None:
        logger.info(f"距离上次直播结束经过了{format_timedelta(dura)}，下播期间收到的礼物￥{offline_income:.2f}")

    async def _on_room_offline(dura: timedelta) -> None:
        logger.info(f"本次直播时长为{format_timedelta(dura)}，共收到的礼物￥{online_income:.2f}")

    async def _on_task_cancel() -> None:
        logger.info(f"未提交的记录：开播期间收到礼物￥{online_income:.2f}，离线期间收到礼物￥{offline_income:.2f}")


    async def _watch_live_status() -> None:
        try:

            while True:

                try:
                    nonlocal is_online
                    if ctx.room_info.is_online != is_online:

                        is_online = ctx.room_info.is_online

                        if is_online:
                            await _on_room_online(ctx.room_info.start_time - ctx.room_info.end_time)
                        else:
                            await _on_room_offline(ctx.room_info.end_time - ctx.room_info.start_time)

                except Exception as e:
                    logger.exception(e)

                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.debug(f"received cancel signal")
            await _on_task_cancel()
            raise


    ctx.add_task(_watch_live_status())


    return handler