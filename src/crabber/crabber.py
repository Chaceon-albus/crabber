import asyncio
import logging
import threading

from datetime import datetime
from typing import Awaitable, Callable, TypeVar

import bilibili_api as biliapi

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api.live import LiveRoom, LiveDanmaku

from crabber.logging import logger
from crabber.credential import CredentialManager
from crabber.room_info import RoomInfo
from crabber.misc import jsonify, safe_ts, check_exceptions
from crabber.database import Database
from crabber.live_stream import LiveStreamManager, StreamStatus
from crabber.services import BaseService, init_services
from crabber.task_manager import TaskManager


TService = TypeVar("TService", bound=BaseService)


class Crabber:


    def __init__(
        self,
        name: str,
        room_id: int,
        cred_manager: CredentialManager,
        database: list | None = None,
        services: list | None = None,
        status_check_interval: int = 120,
    ) -> None:

        self.logger = logger.getChild(f"({name})")

        self.uid = -1
        self.name = name
        self.room_id = room_id
        self.room_info = RoomInfo(id=room_id)
        self.scheduler: AsyncIOScheduler | None = None
        self.cred_manager = cred_manager

        self._db_config = database or []
        self.db: Database | None = None

        self.danmaku: biliapi.live.LiveDanmaku | None = None

        self.loop: asyncio.AbstractEventLoop | None = None
        self.refresh_event: asyncio.Event | None = None

        self.jobs: list[Job] = []
        self.task_manager = TaskManager(logger=self.logger)
        self.online_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []
        self.offline_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []
        self.streaming_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []
        self.room_change_callbacks: list[Callable[[RoomInfo], asyncio._CoroutineLike]] = []

        self._is_cleaned_up = False
        self._services_config = services or []
        self.services: dict[str, BaseService] = {} # key: type -> value: Service class

        self.status_check_interval = status_check_interval
        self.recovery_event = asyncio.Event()
        self.recovery_event.set()

        self._is_ready = threading.Event()

        self.thread = threading.Thread(
            target=self._thread_entry,
            name=f"Thread-{self.name}",
            daemon=True,
        )
        self.__init_time = datetime.now()
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


    def add_task(self, task: Awaitable | Callable, *args, **kwargs) -> asyncio.Task:
        if self.loop is None or not self.loop.is_running():
            raise RuntimeError("crabber is not ready to add task")

        scheduled_task = self.task_manager.go(task, *args, **kwargs)

        self.logger.debug(f"added task {scheduled_task.get_name()}")
        return scheduled_task


    def get_service(self, service_type: type[TService]) -> TService | None:
        service_name = service_type.service_name

        if not service_name:
            self.logger.warning(f"{service_type.__name__} does not define service_name")
            return None

        service = self.services.get(service_name)

        if service is None:
            self.logger.warning(f"{service_name} service not found")
            return None

        if not isinstance(service, service_type):
            self.logger.warning(
                f"{service_name} service has unexpected type: {type(service).__name__}"
            )
            return None

        return service


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
        self.task_manager.bind(self.loop)
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
                self.loop.run_until_complete(self._shutdown())
            except Exception as e:
                self.logger.error(f"error during cleanup: {e}")
            finally:
                self.loop.close()
                self.logger.debug(f"loop stopped")


    async def _bootstrap(self) -> None:

        self.db = Database(self._db_config, self.logger)

        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

        self.services = await init_services(self._services_config, self.logger)

        biliapi.select_client("aiohttp") # httpx does not support websocket

        self.danmaku = LiveDanmaku(self.room_id, credential=self.cred_manager.credential)

        self.danmaku.logger = self.logger.getChild("Danmaku")
        self.danmaku.logger.setLevel(logging.INFO)

        self.room_info.stream = LiveStreamManager(ctx=self)

        await self._update_room_info() # update room_info once before self.start()

        self.add_task(self._listen_refresh_events())  # listen for credential refresh events in the background
        self.add_task(self._keep_danmaku_connected()) # run danmaku connection in the background

        live_status_handler = self._get_live_status_handler()
        for event_name in ["LIVE", "PREPARING", "ROOM_CHANGE", "CHANGE_ROOM_INFO"]:
            self.add_handler(event_name, live_status_handler)


    async def _update_room_info(self) -> None: # no exception will be raised

        attempt = 0
        max_attempt = 3
        room_info = {}

        try:

            while attempt < max_attempt and not room_info:
                attempt += 1
                try:
                    room_info = await self.room.get_room_info() # type: ignore
                except Exception as e:
                    self.logger.error(f"[{attempt}/{max_attempt}] failed to update room info: {e!r}")
                    await asyncio.sleep(3*attempt) # 3s, 6s, 9s

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
            self.logger.exception(f"failed to write room info: {e}")
        else:
            self.logger.debug(f"update room info: {self.room_info}")
        finally:
            if self.uid < 0:
                logger.warning("failed to update uid via get_room_info()")


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

                elif danmaku_status in [
                        self.danmaku.STATUS_CONNECTING,  # 1
                        self.danmaku.STATUS_ESTABLISHED, # 2
                        self.danmaku.STATUS_CLOSING,     # 3
                    ]:
                        # if danmaku is in these states, it should not be here, reset the status just in case
                        self.logger.warning(f"reset danmaku status: {self.danmaku.get_status()} -> STATUS_ERROR")
                        self.danmaku._LiveDanmaku__status = self.danmaku.STATUS_CLOSED # type: ignore

                else:
                    self.logger.warning(f"unknown danmaku status: {self.danmaku.get_status()}, reset to STATUS_ERROR")
                    self.danmaku._LiveDanmaku__status = self.danmaku.STATUS_ERROR # type: ignore

            await asyncio.sleep(1)


    async def _listen_refresh_events(self) -> None:

        while True:
            if not self.refresh_event:
                await asyncio.sleep(1)
                continue

            await self.refresh_event.wait()
            self.refresh_event.clear()

            try:
                if self.danmaku and self.cred_manager.credential:
                    self.logger.debug("updating credential from cred_manager...")
                    self.danmaku.room = LiveRoom(self.room_id, credential=self.cred_manager.credential)
                    self.danmaku.credential = self.cred_manager.credential
                    # await self.danmaku.disconnect() # do we need to force a reconnect?
            except Exception as e:
                self.logger.exception(f"error occurred while handling credential update: {e}")


    async def _on_room_online(self) -> None:
        if not self.online_callbacks: return
        results = await asyncio.gather(
            *[callback(self.room_info) for callback in self.online_callbacks],
            return_exceptions=True,
        )
        check_exceptions(results, msg="failed on online callback", logger=self.logger)

    async def _on_room_offline(self) -> None:
        if not self.offline_callbacks: return
        results = await asyncio.gather(
            *[callback(self.room_info) for callback in self.offline_callbacks],
            return_exceptions=True,
        )
        check_exceptions(results, msg="failed on offline callback", logger=self.logger)

    async def _on_room_streaming(self) -> None:
        if not self.streaming_callbacks: return
        results = await asyncio.gather(
            *[callback(self.room_info) for callback in self.streaming_callbacks],
            return_exceptions=True,
        )
        check_exceptions(results, msg="failed on streaming callback", logger=self.logger)

    async def _on_room_change(self) -> None:
        if not self.room_change_callbacks: return
        results = await asyncio.gather(
            *[callback(self.room_info) for callback in self.room_change_callbacks],
            return_exceptions=True,
        )
        check_exceptions(results, msg="failed on room change callback", logger=self.logger)

    def _get_live_status_handler(self) -> Callable[[dict], asyncio._CoroutineLike]:

        async def handler(event: dict) -> None:

            if (room_real_id:=event.get("room_real_id", -1)) != self.room_id:
                self.logger.debug(f"ignoring live status related event: {room_real_id} != {self.room_id}\n{jsonify(event)}")
                return

            if self.room_info.stream is None: self.room_info.stream = LiveStreamManager(ctx=self) # make linter happy

            data = event.get("data", {})
            cmd = data.get("cmd", "")

            is_currently_online = self.room_info.is_online
            stream_status = self.room_info.stream.status

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
                    elif stream_status != StreamStatus.STREAMING:
                        self.room_info.stream.status = StreamStatus.STREAMING
                        await self._on_room_streaming()
                    else:
                        self.logger.debug("ignoring duplicate LIVE event while stream handler is already running")

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

                    _ = await asyncio.gather(
                        self._on_room_change(), # no exception
                        self._update_room_info(), # no exception
                    )

                case "CHANGE_ROOM_INFO":
                    # relatively rare event, may be received when the streamer changes the cover
                    self.logger.info(f"received CHANGE_ROOM_INFO event with data: {data}")
                    self.room_info.cover = data.get("background") or self.room_info.cover
                    await self._on_room_change()

                case _:
                    self.logger.debug(f"received unhandled live status related event:\n{jsonify(event)}")

        handler.__name__ = "crabber._live_status_handler"

        return handler


    @property
    def room(self) -> LiveRoom | None:
        if self.danmaku is None: return None
        if (
            self.danmaku.room is None
            or (
                self.cred_manager.credential
                and self.danmaku.room.credential is not self.cred_manager.credential
            )
        ):
            self.danmaku.room = LiveRoom(self.room_id, credential=self.cred_manager.credential)
        return self.danmaku.room

    @property
    def has_credential(self) -> bool:
        room = self.room
        return True if room and room.credential.has_sessdata() else False

    @property
    def init_time(self) -> datetime:
        return self.__init_time


    async def _check_live_status(self) -> None:
        is_currently_online = self.room_info.is_online
        await self._update_room_info()

        # check transition from online to offline (missed PREPARING)
        if is_currently_online and not self.room_info.is_online:
            self.logger.info("detected room offline during status check")
            self.room_info.end_time = datetime.now()
            if self.room_info.stream:
                self.room_info.stream.status = StreamStatus.OFFLINE
            await self._on_room_offline()


    async def _check_missed_preparing_on_startup(self) -> None:
        if not self.db: return

        try:
            last_record = await self.db.get_latest_live_record(self.room_id)
            if last_record:
                start_time = last_record.get("start_time")
                end_time = last_record.get("end_time")
                # end_time <= start_time -> not offline
                # not self.room_info.is_online -> room is offline
                # which means we missed an offline event
                if start_time and end_time and end_time <= start_time and not self.room_info.is_online:
                    self.logger.info(f"fetected missed offline event (start_time={start_time}, end_time={end_time}).")
                    self.room_info.start_time = start_time
                    self.room_info.end_time = datetime.now()

                    try:
                        # in case gift logger is not enabled
                        await asyncio.wait_for(self.recovery_event.wait(), 10)
                    except Exception:
                        pass
                    finally:
                        self.logger.info("trigger offline callbacks...")
                        await self._on_room_offline()
        except Exception as e:
            self.logger.exception(f"failed to check missed offline on startup: {e}")


    def start(self) -> None:
        if self.room_info.is_online and self.loop and self.loop.is_running():
            self.logger.info("room is online before the program start")
            asyncio.run_coroutine_threadsafe(self._on_room_online(), self.loop)
            asyncio.run_coroutine_threadsafe(self._on_room_streaming(), self.loop) # assume that it's streaming

        if self.loop and self.loop.is_running():
            self.add_job(
                self._check_live_status,
                trigger="interval",
                seconds=self.status_check_interval,
                next_run_time=datetime.now(),
            )
            self.add_task(self._check_missed_preparing_on_startup())


    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
            try:
                future.result(timeout=15)
            except Exception as e:
                self.logger.error(f"error during shutdown: {e}")
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.logger.info(f"stopping crabber...")
            self.thread.join(timeout=15)


    async def _shutdown(self) -> None:
        if self._is_cleaned_up: return
        self._is_cleaned_up = True

        for job in self.jobs:
            try:
                job.remove()
            except Exception as e:
                self.logger.debug(f"failed to remove job during shutdown: {e}")

        self.jobs.clear()

        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

        await self.task_manager.close()

        if self.room_info.stream:
            await self.room_info.stream.close()

        if self.danmaku:
            await self.danmaku.disconnect()

        service_close_tasks = [service.close() for service in self.services.values()]
        if service_close_tasks:
            results = await asyncio.gather(*service_close_tasks, return_exceptions=True)
            check_exceptions(results, msg="failed to close service", logger=self.logger)


if __name__ == "__main__":
    pass
