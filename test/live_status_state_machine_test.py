from __future__ import annotations

# ruff: noqa: E402, SLF001
# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false

import asyncio
import logging
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crabber.crabber import Crabber
from crabber.live_stream import LiveStreamManager, StreamStatus
from crabber.room_info import RoomInfo
from crabber.components import chatter, gift_logger, recorder
from crabber.database.sqlite import SqliteAdapter


logging.basicConfig(level=logging.CRITICAL)
LOGGER = logging.getLogger("live-status-state-machine-test")


def room_response(live_status: int, *, title: str = "title", start_time: int = 1_700_000_000) -> dict[str, Any]:
    return {
        "anchor_info": {"base_info": {"uname": "anchor"}},
        "room_info": {
            "uid": 42,
            "area_name": "area",
            "title": title,
            "cover": "cover",
            "live_status": live_status,
            "live_start_time": start_time,
        },
    }


class FakeRoom:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.last = responses[-1] if responses else room_response(0)

    async def get_room_info(self) -> dict[str, Any]:
        if self.responses:
            self.last = self.responses.pop(0)
        return self.last


class FakeStream:
    def __init__(self, available: list[bool] | None = None) -> None:
        self.status = StreamStatus.OFFLINE
        self.available = list(available or [])
        self.probe_count = 0
        self.current_format = "flv"
        self.subscribers: list[asyncio.Queue] = []
        self.restart_reasons: list[str] = []

    async def has_available_stream(self) -> bool:
        self.probe_count += 1
        return self.available.pop(0) if self.available else False

    def subscribe(self, q: asyncio.Queue | None = None) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=128) if q is None else q
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    def request_restart(self, reason: str) -> None:
        self.restart_reasons.append(reason)


class FakeSchedulerJob:
    def __init__(self) -> None:
        self.removed = False

    def remove(self) -> None:
        self.removed = True


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[FakeSchedulerJob] = []
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any], int]] = []

    def add_job(self, *args, **kwargs) -> FakeSchedulerJob:
        self.calls.append((args, kwargs, threading.get_ident()))
        job = FakeSchedulerJob()
        self.jobs.append(job)
        return job


def make_crabber(
    responses: list[dict[str, Any]],
    *,
    available: list[bool] | None = None,
    started: bool = True,
) -> tuple[Crabber, FakeStream, list[str]]:
    ctx = object.__new__(Crabber)
    ctx.logger = LOGGER
    ctx.uid = -1
    ctx.name = "test"
    ctx.room_id = 100
    ctx.room_info = RoomInfo(id=100)
    stream = FakeStream(available)
    ctx.room_info.stream = stream
    ctx.cred_manager = SimpleNamespace(credential=None)
    ctx.danmaku = SimpleNamespace(room=FakeRoom(responses))
    ctx.online_callbacks = []
    ctx.offline_callbacks = []
    ctx.streaming_callbacks = []
    ctx.room_change_callbacks = []
    ctx._is_started = started

    events: list[str] = []

    async def online(_: RoomInfo) -> None:
        events.append("online")

    async def offline(_: RoomInfo) -> None:
        events.append("offline")

    async def streaming(_: RoomInfo) -> None:
        events.append("streaming")

    async def room_change(_: RoomInfo) -> None:
        events.append("room_change")

    ctx.online_callbacks.append(online)
    ctx.offline_callbacks.append(offline)
    ctx.streaming_callbacks.append(streaming)
    ctx.room_change_callbacks.append(room_change)
    return ctx, stream, events


async def test_check_live_status_transitions() -> None:
    ctx, stream, events = make_crabber(
        [
            room_response(0),
            room_response(1),
            room_response(1),
            room_response(1),
            room_response(0),
            room_response(0),
        ],
        available=[False, True],
    )

    await ctx.check_live_status(dispatch_callbacks=False)
    assert events == []
    assert ctx.room_info.is_online is False
    assert stream.status == StreamStatus.OFFLINE

    await ctx.check_live_status()
    assert events == ["online"]
    assert ctx.room_info.is_online is True
    assert stream.status == StreamStatus.ONLINE
    assert stream.probe_count == 1

    await ctx.check_live_status()
    assert events == ["online", "streaming"]
    assert stream.status == StreamStatus.STREAMING
    assert stream.probe_count == 2

    await ctx.check_live_status()
    assert events == ["online", "streaming"]
    assert stream.probe_count == 2

    await ctx.check_live_status()
    assert events == ["online", "streaming", "offline"]
    assert ctx.room_info.is_online is False
    assert stream.status == StreamStatus.OFFLINE

    await ctx.check_live_status()
    assert events == ["online", "streaming", "offline"]


async def test_live_events_before_start_do_not_dispatch_callbacks() -> None:
    ctx, stream, events = make_crabber([room_response(0)], started=False)
    handler = ctx._get_live_status_handler()

    await handler({"room_real_id": 100, "data": {"cmd": "LIVE", "live_time": 1_700_000_000}})
    await handler({"room_real_id": 100, "data": {"cmd": "LIVE"}})
    assert ctx.room_info.is_online is True
    assert stream.status == StreamStatus.ONLINE
    assert events == []

    await handler({"room_real_id": 100, "data": {"cmd": "PREPARING", "send_time": 1_700_000_100_000}})
    assert ctx.room_info.is_online is False
    assert stream.status == StreamStatus.OFFLINE
    assert events == []


async def test_live_events_after_start_dispatch_once() -> None:
    ctx, stream, events = make_crabber([room_response(0)], started=True)
    handler = ctx._get_live_status_handler()

    await handler({"room_real_id": 100, "data": {"cmd": "LIVE", "live_time": 1_700_000_000}})
    assert events == ["online"]
    assert stream.status == StreamStatus.ONLINE

    await handler({"room_real_id": 100, "data": {"cmd": "LIVE"}})
    assert events == ["online", "streaming"]
    assert stream.status == StreamStatus.STREAMING

    await handler({"room_real_id": 100, "data": {"cmd": "LIVE"}})
    assert events == ["online", "streaming"]

    await handler({"room_real_id": 100, "data": {"cmd": "PREPARING", "send_time": 1_700_000_100_000}})
    assert events == ["online", "streaming", "offline"]
    assert stream.status == StreamStatus.OFFLINE

    await handler({"room_real_id": 100, "data": {"cmd": "PREPARING", "send_time": 1_700_000_100_000}})
    assert events == ["online", "streaming", "offline"]


async def test_live_events_accept_real_id_for_display_room_id() -> None:
    ctx, stream, events = make_crabber([room_response(0)], started=True)
    ctx.room_id = 12345  # configured display (short) ID
    handler = ctx._get_live_status_handler()

    await handler({"room_real_id": 67890, "data": {"cmd": "LIVE", "live_time": 1_700_000_000}})

    assert events == ["online"]
    assert ctx.room_info.is_online is True
    assert stream.status == StreamStatus.ONLINE


async def test_add_job_registers_coroutine_on_crabber_loop() -> None:
    ctx = object.__new__(Crabber)
    ctx.logger = LOGGER
    ctx.loop = asyncio.get_running_loop()
    ctx.scheduler = FakeScheduler()
    ctx.jobs = []
    ran = 0
    loop_thread_id = threading.get_ident()

    async def check_status() -> None:
        nonlocal ran
        ran += 1

    job = await asyncio.to_thread(ctx.add_job, check_status, "interval", seconds=60)

    assert job is ctx.scheduler.jobs[0]
    args, kwargs, registered_thread_id = ctx.scheduler.calls[0]
    assert args[0] is check_status
    assert kwargs["seconds"] == 60
    assert registered_thread_id == loop_thread_id
    await args[0]()
    assert ran == 1


async def test_gift_events_wait_for_state_recovery() -> None:
    class FakeGiftDatabase:
        def __init__(self) -> None:
            self.recovery_started = asyncio.Event()
            self.release_recovery = asyncio.Event()
            self.recorded_gifts: list[dict[str, Any]] = []
            self.updated_stats: list[dict[str, Any]] = []

        async def get_gift_summary(self, *_: Any) -> dict[str, Any]:
            self.recovery_started.set()
            await self.release_recovery.wait()
            return {"gift_revenue": Decimal("10"), "guard_revenue": Decimal(0), "sc_revenue": Decimal(0)}

        async def record_gift(self, **kwargs: Any) -> None:
            self.recorded_gifts.append(kwargs)

        async def update_stats(self, **kwargs: Any) -> None:
            self.updated_stats.append(kwargs)

    database = FakeGiftDatabase()
    info = RoomInfo(id=100, is_online=True)
    ctx = SimpleNamespace(
        logger=LOGGER,
        room_id=100,
        room_info=info,
        db=database,
        recovery_event=asyncio.Event(),
        tasks=[],
        online_callbacks=[],
        offline_callbacks=[],
    )

    def add_task(coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        ctx.tasks.append(task)
        return task

    ctx.add_task = add_task
    ctx.add_online_callback = ctx.online_callbacks.append
    ctx.add_offline_callback = ctx.offline_callbacks.append

    handler = gift_logger.get_handler(ctx)
    await database.recovery_started.wait()
    gift_task = asyncio.create_task(handler({
        "data": {"cmd": "SEND_GIFT", "data": {"price": 5_000, "num": 1}},
    }))
    await asyncio.sleep(0)
    assert database.recorded_gifts == []

    database.release_recovery.set()
    await gift_task
    assert len(database.recorded_gifts) == 1

    await ctx.offline_callbacks[0](info)
    assert database.updated_stats[0]["gift_revenue"] == Decimal("15")

    for task in ctx.tasks:
        task.cancel()
    await asyncio.gather(*ctx.tasks, return_exceptions=True)


async def test_gift_logger_marks_new_live_record_as_open() -> None:
    class FakeGiftDatabase:
        def __init__(self) -> None:
            self.recorded_stats: list[dict[str, Any]] = []

        async def get_latest_live_record(self, *_: Any) -> None:
            return None

        async def get_gift_summary(self, *_: Any) -> dict[str, Decimal]:
            return {
                "gift_revenue": Decimal(0),
                "guard_revenue": Decimal(0),
                "sc_revenue": Decimal(0),
            }

        async def record_stats(self, **kwargs: Any) -> None:
            self.recorded_stats.append(kwargs)

    database = FakeGiftDatabase()
    info = RoomInfo(
        id=100,
        is_online=False,
        start_time=datetime.fromtimestamp(1_700_000_000),
    )
    ctx = SimpleNamespace(
        logger=LOGGER,
        room_id=100,
        room_info=info,
        db=database,
        tasks=[],
        online_callbacks=[],
        offline_callbacks=[],
    )

    def add_task(coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        ctx.tasks.append(task)
        return task

    ctx.add_task = add_task
    ctx.add_online_callback = ctx.online_callbacks.append
    ctx.add_offline_callback = ctx.offline_callbacks.append

    gift_logger.get_handler(ctx)
    await ctx.online_callbacks[0](info)

    assert database.recorded_stats[0]["end_time"].timestamp() == 0

    for task in ctx.tasks:
        task.cancel()
    await asyncio.gather(*ctx.tasks, return_exceptions=True)


async def test_sqlite_migrates_live_record_danmaku_count() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        database_path = Path(tmpdir) / "legacy.sqlite"
        with closing(sqlite3.connect(database_path)) as conn:
            conn.execute(
                "CREATE TABLE live_record (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL)"
            )
            conn.execute("INSERT INTO live_record (room_id) VALUES (100)")
            conn.commit()

        adapter = SqliteAdapter({"path": str(database_path)}, LOGGER)
        await adapter._ensure_init()
        await adapter.close()

        with closing(sqlite3.connect(database_path)) as conn:
            columns = {
                row[1]: row
                for row in conn.execute("PRAGMA table_info(live_record)")
            }
            danmaku_count = conn.execute(
                "SELECT danmaku_count FROM live_record WHERE room_id=100"
            ).fetchone()

        assert columns["danmaku_count"][3] == 1
        assert columns["danmaku_count"][4] == "0"
        assert danmaku_count == (0,)


async def test_sqlite_counts_danmaku_when_live_ends() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        database_path = Path(tmpdir) / "current.sqlite"
        adapter = SqliteAdapter({"path": str(database_path)}, LOGGER)
        start_time = datetime.fromtimestamp(1_700_000_000)
        end_time = start_time + timedelta(minutes=1)

        await adapter.record_stats(
            room_id=100,
            title="title",
            area="area",
            cover_url="cover",
            start_time=start_time,
            end_time=datetime.fromtimestamp(0, timezone.utc),
            offline_gift_revenue=Decimal(0),
            offline_guard_revenue=Decimal(0),
            offline_sc_revenue=Decimal(0),
            gift_revenue=Decimal(0),
            guard_revenue=Decimal(0),
            sc_revenue=Decimal(0),
            summary="",
            details={},
        )
        await adapter.record_danmaku(
            room_id=100,
            user="viewer",
            uid=1000,
            content="first",
            timestamp=start_time,
        )
        await adapter.record_danmaku(
            room_id=100,
            user="viewer",
            uid=1000,
            content="second",
            timestamp=end_time,
        )
        await adapter.record_danmaku(
            room_id=100,
            user="viewer",
            uid=1000,
            content="too early",
            timestamp=start_time - timedelta(seconds=1),
        )
        await adapter.record_danmaku(
            room_id=100,
            user="viewer",
            uid=1000,
            content="too late",
            timestamp=end_time + timedelta(seconds=1),
        )
        await adapter.record_danmaku(
            room_id=101,
            user="viewer",
            uid=1000,
            content="other room",
            timestamp=start_time,
        )

        await adapter.update_stats(
            room_id=100,
            start_time=start_time,
            end_time=end_time,
            gift_revenue=Decimal(0),
            guard_revenue=Decimal(0),
            sc_revenue=Decimal(0),
            summary="",
            details={},
        )
        latest_record = await adapter.get_latest_live_record(100)
        await adapter.close()

        with closing(sqlite3.connect(database_path)) as conn:
            live_record = conn.execute(
                "SELECT end_time, danmaku_count FROM live_record WHERE room_id=100"
            ).fetchone()

        assert live_record == (int(end_time.timestamp()), 2)
        assert latest_record and latest_record["danmaku_count"] == 2


async def test_recorder_subscribes_without_live_network() -> None:
    ctx = SimpleNamespace(
        logger=LOGGER,
        room_info=RoomInfo(id=100, title="recording"),
        tasks=[],
    )
    stream = FakeStream()
    ctx.room_info.stream = stream

    def add_task(coro):
        task = asyncio.create_task(coro)
        ctx.tasks.append(task)
        return task

    ctx.add_task = add_task

    with tempfile.TemporaryDirectory() as tmpdir:
        recorder.get_handler(ctx, path=tmpdir) # type: ignore
        await asyncio.sleep(0)
        assert len(stream.subscribers) == 1

    for task in ctx.tasks:
        task.cancel()
    await asyncio.gather(*ctx.tasks, return_exceptions=True)


async def test_chatter_registers_and_cleans_cron_jobs() -> None:
    ctx = SimpleNamespace(
        logger=LOGGER,
        room_info=RoomInfo(id=100, title="chat"),
        scheduler=FakeScheduler(),
        online_callbacks=[],
        offline_callbacks=[],
        room_id=100,
    )

    def add_online_callback(callback):
        ctx.online_callbacks.append(callback)

    def add_offline_callback(callback):
        ctx.offline_callbacks.append(callback)

    ctx.add_online_callback = add_online_callback
    ctx.add_offline_callback = add_offline_callback

    chatter.get_handler(
        ctx, # type: ignore
        on_cron=[{"interval": {"seconds": 60}, "message": "tick"}],
    )

    assert len(ctx.online_callbacks) == 1
    assert len(ctx.offline_callbacks) == 1

    await ctx.online_callbacks[0](ctx.room_info)
    assert len(ctx.scheduler.jobs) == 1
    assert ctx.scheduler.jobs[0].removed is False

    await ctx.offline_callbacks[0](ctx.room_info)
    assert ctx.scheduler.jobs[0].removed is True


async def test_dispatch_stops_immediately_when_offline() -> None:
    class FakeContent:
        def __init__(self) -> None:
            self.read_count = 0

        async def readany(self) -> bytes:
            self.read_count += 1
            return b"data"

    class FakeResponse:
        def __init__(self) -> None:
            self.content = FakeContent()
            self.released = False

        def release(self) -> None:
            self.released = True

    ctx = SimpleNamespace(logger=LOGGER, room_info=RoomInfo(id=100, is_online=False))
    manager = object.__new__(LiveStreamManager)
    manager.ctx = ctx
    manager.status = StreamStatus.OFFLINE
    manager._restart_requested = None
    queue = asyncio.Queue()
    manager.subscribers = [queue]
    manager._full_subscriber_log_state = {}

    response = FakeResponse()
    await manager._dispatch(response) # type: ignore

    assert response.content.read_count == 0
    assert response.released is True
    assert await queue.get() is None


async def main() -> None:
    tests = [
        test_check_live_status_transitions,
        test_live_events_before_start_do_not_dispatch_callbacks,
        test_live_events_after_start_dispatch_once,
        test_live_events_accept_real_id_for_display_room_id,
        test_add_job_registers_coroutine_on_crabber_loop,
        test_gift_events_wait_for_state_recovery,
        test_gift_logger_marks_new_live_record_as_open,
        test_sqlite_migrates_live_record_danmaku_count,
        test_sqlite_counts_danmaku_when_live_ends,
        test_recorder_subscribes_without_live_network,
        test_chatter_registers_and_cleans_cron_jobs,
        test_dispatch_stops_immediately_when_offline,
    ]

    for test in tests:
        await test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    asyncio.run(main())
