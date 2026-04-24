import asyncio
import logging
import threading

from datetime import datetime
from typing import Optional, Callable

import bilibili_api as biliapi

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api.live import LiveRoom, LiveDanmaku

from crabber.logging import logger
from crabber.credential import CredentialManager
from crabber.room_info import RoomInfo
from crabber.misc import jsonify, safe_ts
from crabber.database import Database
from crabber.live_stream import LiveStream, StreamStatus
from crabber.services import BaseService, init_services


class Crabber:


    def __init__(self, name: str, room_id: int, cred_manager: CredentialManager, database: list = [], services: list = []) -> None:

        self.logger = logger.getChild(f"({name})")

        self.uid = -1
        self.name = name
        self.room_id = room_id
        self.room_info = RoomInfo(id=room_id)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.cred_manager = cred_manager

        self._db_config = database
        self.db: Optional[Database] = None

        self.danmaku: Optional[biliapi.live.LiveDanmaku] = None

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.refresh_event: Optional[asyncio.Event] = None

        self.jobs: list[Job] = []
        self.tasks: list[asyncio.Task] = []
        self.online_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []
        self.offline_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []
        self.streaming_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []
        self.room_change_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []

        self._services_config = services
        self.services: dict[str, BaseService] = {} # key: type -> value: Service class

        self._is_ready = threading.Event()

        self.thread = threading.Thread(
            target=self._thread_entry,
            name=f"Thread-{self.name}",
            daemon=True,
        )
        self.thread.start()

        self._is_ready.wait() # wait until the thread is ready


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


    def add_online_callback(self, callback: Callable[[RoomInfo], asyncio._CoroutineLike]) -> None:
        self.online_callbacks.append(callback)
        self.logger.debug(f"added online callback: {callback.__name__}")


    def add_offline_callback(self, callback: Callable[[RoomInfo], asyncio._CoroutineLike]) -> None:
        self.offline_callbacks.append(callback)
        self.logger.debug(f"added offline callback: {callback.__name__}")

    def add_streaming_callback(self, callback: Callable[[RoomInfo], asyncio._CoroutineLike]) -> None:
        self.streaming_callbacks.append(callback)
        self.logger.debug(f"added streaming callback: {callback.__name__}")

    def add_room_change_callback(self, callback: Callable[[RoomInfo], asyncio._CoroutineLike]) -> None:
        self.room_change_callbacks.append(callback)
        self.logger.debug(f"added room change callback: {callback.__name__}")


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

        self.db = Database(self._db_config, self.logger)

        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

        self.services = await init_services(self._services_config, self.logger)

        biliapi.select_client("aiohttp") # httpx does not support websocket

        self.danmaku = LiveDanmaku(self.room_id, credential=self.cred_manager.credential)

        self.danmaku.logger = self.logger.getChild("Danmaku")
        self.danmaku.logger.setLevel(logging.INFO)

        self.room_info.stream = LiveStream(ctx=self)

        self.add_task(self._listen_refresh_events())  # listen for credential refresh events in the background
        self.add_task(self._keep_danmaku_connected()) # run danmaku connection in the background

        live_status_handler = self._get_live_status_handler()
        for event_name in ["LIVE", "PREPARING", "ROOM_CHANGE", "CHANGE_ROOM_INFO"]:
            self.add_handler(event_name, live_status_handler)


    async def _update_room_info(self) -> None: # no exception will be raised
        try:
            room_info   = await self.room.get_room_info() # type: ignore
            anchor_info = room_info.get("anchor_info", {})
            room_info   = room_info.get("room_info", {})

            self.uid = room_info.get("uid", self.uid)
            self.room_info.area = room_info.get("area_name", self.room_info.area)
            self.room_info.uname = anchor_info.get("base_info", {}).get("uname", self.room_info.uname)
            self.room_info.title = room_info.get("title", self.room_info.title)
            self.room_info.cover = room_info.get("cover", self.room_info.cover)
            self.room_info.is_online = (room_info.get("live_status", 0) == 1)

            if self.room_info.is_online:
                self.room_info.start_time = datetime.fromtimestamp(
                    room_info.get("live_start_time", int(datetime.now().timestamp()))
                )
                # if the room is already online, we assume it's streaming,
                # since this function is called when the crabber is started or reconnected
                if self.room_info.stream: # make linter happy
                    self.room_info.stream.status = StreamStatus.STREAMING
        except Exception as e:
            self.logger.exception(f"failed to update room info: {e}")
        else:
            self.logger.debug(f"update room info: {self.room_info}")


    async def _keep_danmaku_connected(self) -> None:
        while True:
            if self.danmaku:
                if (danmaku_status:=self.danmaku.get_status()) in [
                    self.danmaku.STATUS_INIT,   # 0
                    self.danmaku.STATUS_CLOSED, # 4
                    self.danmaku.STATUS_ERROR   # 5
                ]:

                    # in case the room status changes while danmaku is not connected
                    await self._update_room_info() # no exception

                    try:
                        await self.danmaku.connect()
                    except Exception as e:
                        self.logger.exception(f"danmaku error: {e}")
                        # TODO: remove the hack to set the __status
                        self.danmaku._LiveDanmaku__status = self.danmaku.STATUS_ERROR # type: ignore

                elif danmaku_status in [
                        self.danmaku.STATUS_CONNECTING,  # 1
                        self.danmaku.STATUS_ESTABLISHED, # 2
                        self.danmaku.STATUS_CLOSING,     # 3
                    ]:
                        # if danmaku is in these states, it should not be here, reset the status
                        # TODO: remove the hack to set the __status
                        self.danmaku._LiveDanmaku__status = self.danmaku.STATUS_CLOSED # type: ignore

                else:
                    self.logger.warning(f"unknown danmaku status: {self.danmaku.get_status()}")
                    # TODO: remove the hack to set the __status
                    self.danmaku._LiveDanmaku__status = self.danmaku.STATUS_ERROR # type: ignore

            await asyncio.sleep(1)


    async def _listen_refresh_events(self) -> None:

        while True:
            if not self.refresh_event:
                await asyncio.sleep(1)
                continue

            await self.refresh_event.wait()
            self.refresh_event.clear()

            if self.danmaku and self.danmaku.credential and self.cred_manager.credential:
                self.logger.debug("updating credential from cred_manager...")
                self.danmaku.room = LiveRoom(self.room_id, credential=self.cred_manager.credential)
                self.danmaku.credential = self.cred_manager.credential
                # await self.danmaku.disconnect() # do we need to force a reconnect?

            try:
                pass
            except Exception as e:
                self.logger.exception(f"error occurred while handling credential update: {e}")


    async def _on_room_online(self) -> None:
        for callback in self.online_callbacks:
            try:
                await callback(self.room_info)
            except Exception as e:
                self.logger.exception(f"failed on online callback: {e}")

    async def _on_room_offline(self) -> None:
        for callback in self.offline_callbacks:
            try:
                await callback(self.room_info)
            except Exception as e:
                self.logger.exception(f"failed on offline callback: {e}")

    async def _on_room_streaming(self) -> None:
        for callback in self.streaming_callbacks:
            try:
                await callback(self.room_info)
            except Exception as e:
                self.logger.exception(f"failed on streaming callback: {e}")

    async def _on_room_change(self) -> None:
        for callback in self.room_change_callbacks:
            try:
                await callback(self.room_info)
            except Exception as e:
                self.logger.exception(f"failed on room change callback: {e}")

    def _get_live_status_handler(self) -> Callable[[dict], asyncio._CoroutineLike]:

        async def handler(event: dict) -> None:

            if (room_real_id:=event.get("room_real_id", -1)) != self.room_id:
                self.logger.debug(f"ignoring live status related event: {room_real_id} != {self.room_id}\n{jsonify(event)}")
                return

            if self.room_info.stream is None: self.room_info.stream = LiveStream(ctx=self) # make linter happy

            data = event.get("data", {})
            cmd = data.get("cmd", "")

            is_currently_online = self.room_info.is_online

            match cmd:

                case "LIVE":
                    self.logger.debug(f"received LIVE event with data: {data}")

                    if "live_time" in data:
                        # multiple events may be received during the live status transition,
                        # but only the first one contains the live_time field,
                        # so it's safe to update start_time whenever it's present
                        self.room_info.start_time = datetime.fromtimestamp(data["live_time"])

                    self.room_info.is_online = True
                    self.room_info.stream.status = StreamStatus.ONLINE

                    if not is_currently_online: # offline -> online
                        await self._on_room_online()
                    else:
                        self.room_info.stream.status = StreamStatus.STREAMING
                        await self._on_room_streaming()

                case "PREPARING":
                    self.logger.debug(f"received PREPARING event with data: {data}")

                    self.room_info.end_time = datetime.fromtimestamp(
                        safe_ts(data.get("send_time", 1000*datetime.now().timestamp()))
                    )
                    self.room_info.is_online = False
                    self.room_info.stream.status = StreamStatus.OFFLINE

                    if is_currently_online: # online -> offline
                        await self._on_room_offline()

                case "ROOM_CHANGE":
                    data = data.get("data", {}) # extra layer for ROOM_CHANGE event
                    self.logger.debug(f"received ROOM_CHANGE event with data: {data}")
                    self.room_info.area = data.get("area_name", self.room_info.area)
                    self.room_info.title = data.get("title", self.room_info.title)
                    await self._on_room_change()

                case "CHANGE_ROOM_INFO":
                    # relatively rare event, may be received when the streamer changes the cover
                    self.logger.info(f"received CHANGE_ROOM_INFO event with data: {data}")
                    self.room_info.cover = data.get("background", self.room_info.cover)
                    await self._on_room_change()

                case _:
                    self.logger.debug(f"received unhandled live status related event:\n{jsonify(event)}")

        handler.__name__ = "crabber._live_status_handler"

        return handler


    @property
    def room(self) -> Optional[LiveRoom]:
        if self.danmaku is None: return None
        if self.danmaku.room is None:
            self.danmaku.room = LiveRoom(self.room_id, credential=self.cred_manager.credential)
        return self.danmaku.room

    @property
    def has_credential(self) -> bool:
        room = self.room
        return True if room and room.credential.has_sessdata() else True


    def start(self) -> None:
        if self.room_info.is_online and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_room_online(), self.loop)
            asyncio.run_coroutine_threadsafe(self._on_room_streaming(), self.loop) # assume that it's streaming


    def stop(self) -> None:
        for job in self.jobs: job.remove()
        for task in self.tasks: task.cancel()
        if self.scheduler and self.scheduler.running: self.scheduler.shutdown(wait=False)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.logger.info(f"stopping crabber...")


if __name__ == "__main__":
    pass
