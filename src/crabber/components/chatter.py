import random
import time

from collections import UserString
from datetime import datetime
from string import Template
from typing import Callable, Awaitable

from apscheduler.job import Job
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from bilibili_api import Danmaku

from crabber.crabber import Crabber
from crabber.room_info import RoomInfo
from crabber.components import empty_handler


default_events = []


def get_handler(ctx: Crabber, on_live: dict = {}, on_cron: list[dict] = [], *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger
    _init_time = time.monotonic()

    welcome_msg = MessageSelector(on_live.get("message", ""), on_live.get("random", False))

    crontab_msg = [
        {
            "schedule": cc.get("schedule", ""),
            "interval": cc.get("interval", {}),
            "message": MessageSelector(cc.get("message", ""), cc.get("random", False)),
        }  for cc in on_cron if cc.get("schedule") or cc.get("interval")
    ]

    crontab_jobs: list[Job] = []


    # sanity check
    for cron in crontab_msg:
        try:
            if (schedule:=cron["schedule"]): CronTrigger.from_crontab(schedule)
            if (interval:=cron["interval"]): IntervalTrigger(**interval)
        except Exception as e:
            logger.error(f"failed to check trigger for {cron}: {e}")


    async def _send_danmaku_noexcept(selector: MessageSelector, info: RoomInfo = ctx.room_info) -> None:
        if not ctx.has_credential or not ctx.room:
            logger.warning("invalid credential or room not initialized, skip")
            return
        try:
            now = datetime.now()
            if msg_content := Template(str(selector)).safe_substitute({
                "room_id": info.id,
                "room_title": info.title,
                "time": now.strftime("%H:%M"),
                "date": now.strftime("%Y/%m/%d"),
            }):
                await ctx.room.send_danmaku(Danmaku(msg_content), info.id)
                logger.info(f"sent danmaku: {msg_content}")
            else:
                logger.warning("skip empty message")
        except Exception as e:
            logger.error(f"failed to send danmaku: {e}")


    async def chatter_online(info: RoomInfo) -> None:

        # if online in 10s after init, it might not be online before start
        elapsed = time.monotonic() - _init_time
        if elapsed > 10: await _send_danmaku_noexcept(welcome_msg, info)

        if not ctx.scheduler:
            logger.error("scheduler not initialized, skip")
            return

        for cron in crontab_msg:
            try:
                schedule = cron["schedule"]
                interval = cron["interval"]

                # if both configured, prefer to use interval
                trigger = IntervalTrigger(**interval) if interval else CronTrigger.from_crontab(schedule)

                crontab_jobs.append(
                    ctx.scheduler.add_job(
                        func=_send_danmaku_noexcept,
                        trigger=trigger,
                        args=[cron["message"]]
                    )
                )
                logger.info(f"added chatter cron task: {cron['schedule']}")
            except Exception as e:
                logger.error(f"failed to add cron task for {cron['schedule']}: {e}")


    async def chatter_offline(_: RoomInfo) -> None:
        job = None
        while crontab_jobs:
            try:
                job = crontab_jobs.pop()
                job.remove()
            except Exception as e:
                logger.error(f"failed to remove {job}: {e}")
            else:
                logger.debug(f"removed chatter cron: {job}")


    ctx.add_online_callback(chatter_online)
    ctx.add_offline_callback(chatter_offline)

    return empty_handler


class MessageSelector(UserString):

    def __init__(self, message: list[str] | str, random: bool = False) -> None:
        self.messages = [message] if isinstance(message, str) else message
        self.random   = random
        self._counter = 0

        initial_data = self.messages[0] if self.messages else ""
        super().__init__(initial_data)

    def _select_next(self) -> str:
        if not self.messages:
            return ""

        if self.random:
            return random.choice(self.messages)
        else:
            idx = self._counter % len(self.messages)
            self._counter += 1
            return self.messages[idx]

    def __str__(self) -> str:
        self.data = self._select_next()
        return self.data

    def __repr__(self) -> str:
        return f"MessageSelector(count={len(self.messages)}, random={self.random}, current={self._counter})"