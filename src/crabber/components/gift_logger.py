from typing import Callable, Awaitable
from crabber.logging import logger
from crabber.misc import coin_to_cny


default_events = ["SEND_GIFT", "USER_TOAST_MSG", "SUPER_CHAT_MESSAGE"]


def get_handler(*args, **kwargs) -> Callable[[dict], Awaitable[None]]:

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


        # value_in_cny...


    return handler