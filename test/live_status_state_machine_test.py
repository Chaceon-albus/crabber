from __future__ import annotations

# ruff: noqa: E402, SLF001
# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false

import asyncio
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crabber.crabber import Crabber
from crabber.live_stream import LiveStreamManager, StreamStatus
from crabber.room_info import RoomInfo
from crabber.components import chatter, recorder


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

    def add_job(self, *args, **kwargs) -> FakeSchedulerJob:
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
        test_recorder_subscribes_without_live_network,
        test_chatter_registers_and_cleans_cron_jobs,
        test_dispatch_stops_immediately_when_offline,
    ]

    for test in tests:
        await test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    asyncio.run(main())
