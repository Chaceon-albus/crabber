import asyncio
import logging
import threading

from typing import Optional, Callable

import bilibili_api as biliapi

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api.live import LiveRoom, LiveDanmaku

from crabber.logging import logger
from crabber.credential import CredentialManager


class Crabber:


    def __init__(self, name: str, room_id: int, cred_manager: CredentialManager) -> None:

        self.logger = logger.getChild(f"({name})")

        self.uid = -1
        self.name = name
        self.room_id = room_id
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.cred_manager = cred_manager

        self.danmaku: Optional[biliapi.live.LiveDanmaku] = None

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.refresh_event: Optional[asyncio.Event] = None

        self.jobs: list[Job] = []
        self.tasks: list[asyncio.Task] = []

        self._is_ready = threading.Event()

        self.thread = threading.Thread(
            target=self._thread_entry,
            name=f"Thread-{self.name}",
            daemon=True,
        )
        self.thread.start()

        self._is_ready.wait() # wait until the thread is ready


    def _thread_entry(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.refresh_event = asyncio.Event()

        # register self to the credential manager for refresh notification
        self.cred_manager.register(
            self.name,
            self.loop,
            self.refresh_event
        )

        try:
            self.logger.debug(f"starting crabber for room {self.room_id}")

            self.loop.run_until_complete(self._bootstrap())
            self._is_ready.set() # signal that the thread is ready

            self.loop.run_forever()
        except Exception as e:
            self.logger.error(e)
        finally:
            try:
                if self.danmaku: self.loop.run_until_complete(self.danmaku.disconnect())
                # self._clean_up_tasks()
            except Exception as e:
                self.logger.error(f"error during cleanup: {e}")
            finally:
                self.loop.close()
                self.logger.debug(f"loop closed")


    async def _bootstrap(self) -> None:

        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

        biliapi.select_client("aiohttp") # httpx does not support websocket

        self.danmaku = LiveDanmaku(self.room_id, credential=self.cred_manager.credential)

        self.danmaku.logger = self.logger.getChild("Danmaku")
        self.danmaku.logger.setLevel(logging.INFO)

        self.add_task(self._keep_danmaku_connected()) # run danmaku connection in the background
        self.add_task(self._listen_refresh_events())  # listen for credential refresh events in the background

        while self.danmaku.get_status() < 2:
            # wait until danmaku is ready
            await asyncio.sleep(1)

        room_info = await self.room.get_room_info() # type: ignore

        # update some information of the crabber after danmaku is ready
        self.uid = room_info.get("room_info", {}).get("uid", -1)


    async def _keep_danmaku_connected(self) -> None:
        while True:
            if self.danmaku:
                if self.danmaku.get_status() in [0, 4, 5]:
                    try:
                        await self.danmaku.connect()
                    except Exception as e:
                        self.logger.exception(f"danmaku error: {e}")

            await asyncio.sleep(1)


    async def _listen_refresh_events(self) -> None:
        # looks like a useless function since credential is a reference
        while True:
            if not self.refresh_event:
                await asyncio.sleep(1)
                continue

            await self.refresh_event.wait()
            self.refresh_event.clear()

            self.logger.debug("credential refresh signal received, applying updates...")

            try:
                pass
            except Exception as e:
                self.logger.exception(f"error occurred while handling credential update: {e}")


    def add_handler(self, event_name: str, handler: Callable):

        if self.loop is None or not self.loop.is_running():
            raise RuntimeError(f"crabber is not ready to add handler")

        def _register():
            if self.danmaku:
                self.danmaku.add_event_listener(event_name, handler)
            else:
                self.logger.error(f"failed to register handler: danmaku is not initialized")

        self.loop.call_soon_threadsafe(_register)
        self.logger.debug(f"registered {handler.__name__} for {event_name}")


    def add_job(self, func, trigger: str = "interval", *args, **kwargs) -> Job:
        if self.loop is None or not self.loop.is_running() or self.scheduler is None:
            raise RuntimeError("crabber is not ready to add job")

        def thread_safe_wrapper(*wrapper_args, **inner_kwargs):
            asyncio.run_coroutine_threadsafe(func(*wrapper_args, **inner_kwargs), self.loop) # type: ignore

        job = self.scheduler.add_job(
            thread_safe_wrapper,
            trigger,
            args=args,
            **kwargs
        )

        self.jobs.append(job)

        self.logger.debug(f"added job {func.__name__} with trigger '{trigger}' and args {kwargs}")
        return job


    def add_task(self, coro: asyncio._CoroutineLike, *args, **kwargs) -> asyncio.Task:
        if self.loop is None or not self.loop.is_running():
            raise RuntimeError("crabber is not ready to add task")

        task = self.loop.create_task(coro, *args, **kwargs)
        self.tasks.append(task)

        self.logger.debug(f"added task {coro.__name__}")
        return task


    @property
    def room(self) -> Optional[LiveRoom]:
        return None if not self.danmaku else self.danmaku.room


    def stop(self) -> None:
        for job in self.jobs: job.remove()
        for task in self.tasks: task.cancel()
        if self.scheduler and self.scheduler.running: self.scheduler.shutdown(wait=False)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.logger.info(f"stopping crabber...")


if __name__ == "__main__":
    pass