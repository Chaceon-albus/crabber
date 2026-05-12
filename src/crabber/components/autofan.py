from datetime import datetime
from typing import Callable, Awaitable

from apscheduler.job import Job
from apscheduler.triggers.cron import CronTrigger

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.components import empty_handler
from crabber.misc import jsonify


default_events = []


def get_handler(ctx: Crabber, gift_num: int = 1, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger

    autofan_job: Job | None = None
    popular_ticket_id: int = -1


    async def _send_popular_ticket_noexcept() -> None:
        if not ctx.has_credential or not ctx.room:
            logger.warning("invalid credential or room not initialized, skip")
            return

        try:
            resp = await ctx.room.send_gift_gold(
                uid=int(ctx.room.credential.dedeuserid), # type: ignore
                gift_id=popular_ticket_id, price=100,
                gift_num=gift_num,
            )
            if send_id := resp.get("send_id", ""):
                logger.info(f"success to send {gift_num}×popular ticket(s): {send_id}")
            else:
                logger.info(f"tried to send {gift_num}×popular ticket(s) and got:\n{jsonify(send_id)}")
        except Exception as e:
            logger.error(f"failed to send popular ticket: {e}")


    async def _update_popular_ticket_id(_: RoomInfo) -> None:
        if not ctx.room: return

        gift_resp = {}

        try:
            gift_resp = await ctx.room.get_gift_common()
            gold_list = gift_resp.get("room_gift_list", {}).get("gold_list", [])

            popular_ticket_ids = [33988, 34391, 34003, 33987, 34003] # some hard code :P

            for gift in gold_list:
                if (gid:=gift.get("gift_id", -1)) in popular_ticket_ids:
                    nonlocal popular_ticket_id
                    popular_ticket_id = gid
                    logger.debug(f"find popular ticket: id={gid}")

            if popular_ticket_id < 0: raise Exception()
        except Exception as e:
            gift_resp_str = "\n"+jsonify(gift_resp) if gift_resp else ""
            logger.error(f"failed to update popular ticket gift id: {e}{gift_resp_str}")


    async def autofan_online(info: RoomInfo) -> None:

        if not ctx.scheduler:
            logger.error("scheduler not initialized, skip")
            return

        await _update_popular_ticket_id(info)

        now = datetime.now()
        if 1 < now.minute < 59 or (now.minute==59 and now.second < 50):
            # send a popular ticket manually
            await _send_popular_ticket_noexcept()

        if autofan_job is None:
            nonlocal autofan_job
            autofan_job = ctx.scheduler.add_job(
                func=_send_popular_ticket_noexcept,
                trigger=CronTrigger.from_crontab("1 * * * *"),
            )
        else:
            logger.warning(f"autofan tried to add the job, but the job already exists")


    async def autofan_offline(_: RoomInfo) -> None:
        nonlocal autofan_job
        try:
            if autofan_job: autofan_job.remove()
        except Exception as e:
            logger.error(f"failed to remove {autofan_job}: {e}")
        finally:
            autofan_job = None


    ctx.add_online_callback(autofan_online)
    ctx.add_offline_callback(autofan_offline)


    return empty_handler
