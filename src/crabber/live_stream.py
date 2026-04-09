from __future__ import annotations

import aiohttp
import asyncio

from enum import Enum
from typing import Callable, Optional, TYPE_CHECKING


if TYPE_CHECKING:
    from crabber.crabber import Crabber
    from crabber.room_info import RoomInfo


class StreamStatus(Enum):
    OFFLINE = -1
    ONLINE = 0
    STREAMING = 1


class LiveStream:

    def __init__(self, ctx: Crabber) -> None:
        self.ctx = ctx

        online_handler = self.get_live_handler()
        self.ctx.add_online_callback(online_handler)

        self.status = StreamStatus.OFFLINE
        self.client: Optional[aiohttp.ClientSession] = None
        self.dispatcher: Optional[asyncio.Task] = None
        self.subscribers: list[asyncio.Queue] = []


    async def get_live_streams(self) -> list[str]:
        urls = []

        try:
            resp: dict = await self.ctx.room.get_room_play_url() # type: ignore
        except Exception as e:
            self.ctx.logger.exception(f"failed to fetch live streams: {e}")
        else:
            urls = [d.get("url") for d in resp.get("durl", []) if "url" in d]

        return urls


    def subscribe(self, q: Optional[asyncio.Queue] = None) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=128) if q is None else q # ~64KB * 128 = 8MB of buffer
        self.subscribers.append(q)
        return q


    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass
        except Exception as e:
            self.ctx.logger.exception(f"failed to notify subscriber: {e}")


    async def download_stream(self, urls: Optional[list[str]] = None, timeout: Optional[aiohttp.ClientTimeout] = None) -> Optional[aiohttp.ClientResponse]:
        streams = urls if urls is not None else await self.get_live_streams()
        timeout = timeout or aiohttp.ClientTimeout(total=None, connect=10.0, sock_read=10.0, sock_connect=10.0)

        if not self.client:
            self.client = aiohttp.ClientSession(
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                    "Referer": f"https://live.bilibili.com/{self.ctx.room_info.id}",
                },
                timeout=timeout,
            )

        for stream in streams:
            self.ctx.logger.debug(f"start to download stream: {stream}")

            resp = None
            try:
                resp = await self.client.get(stream, timeout=timeout, ssl=False) # some cdn may have invalid ssl certs
                resp.raise_for_status()
            except Exception as e:
                self.ctx.logger.exception(f"failed to download stream: {e}")
                if resp is not None:
                    await resp.release()
            else:
                return resp

        return None


    def get_live_handler(self) -> Callable[[RoomInfo], asyncio._CoroutineLike]:

        ctx = self.ctx

        async def handler(_) -> None:

            if self.dispatcher and not self.dispatcher.done():
                ctx.logger.warning(f"live stream handler is already running, skipping...")
                return

            async def _dispatch_worker() -> None:
                is_first_attempt = True
                is_empty_streams = False

                try:
                    while self.status != StreamStatus.OFFLINE:

                        if not self.subscribers:
                            await asyncio.sleep(1) # if no subscribers, wait until there is at least one subscriber
                            continue

                        stream = None

                        try:

                            # StreamStatus.ONLINE means:
                            # the room is live before the program starts (first attempt to download stream)
                            # or
                            # the room just turned live but not started streaming (first attempt will fail and retry after 10 seconds)
                            if self.status == StreamStatus.ONLINE:
                                if not is_first_attempt:
                                    if is_empty_streams:
                                        await asyncio.sleep(1) # wait a bit before retrying
                                        continue # if the stream is empty, wait until StreamStatus.STREAMING
                                    else:
                                        await asyncio.sleep(10) # wait a bit before retrying
                                else:
                                    is_first_attempt = False

                            if (stream_urls := await self.get_live_streams()):
                                is_empty_streams = False
                                self.status = StreamStatus.STREAMING
                                if (stream:=await self.download_stream(urls=stream_urls)) is not None:
                                    ctx.logger.debug(f"successfully start downloading live stream, start dispatching")
                                    await self._dispatch(stream)
                                else:
                                    ctx.logger.warning(f"failed to download live stream, retrying in 5 seconds...")
                                    await asyncio.sleep(5)
                            else:
                                is_empty_streams = True # no stream urls available, will retry in the next loop
                                await asyncio.sleep(1)

                        except Exception as e:
                            ctx.logger.exception(f"error in live stream handler: {e}")
                        finally:
                            if stream is not None: await stream.release()

                finally:
                    self.dispatcher = None


            self.dispatcher = asyncio.create_task(_dispatch_worker())


        handler.__name__ = "[LiveStream]on_live_start"
        return handler


    async def _dispatch(self, stream: aiohttp.ClientResponse) -> None:

        try:
            while True:

                if not (subs:= list(self.subscribers)): break

                try:
                    chunk = await stream.content.readany()
                except Exception as e:
                    self.ctx.logger.exception(f"failed to read chunk from stream: {e}")
                    break
                else:
                    if not chunk: break

                    for q in subs:
                        try:
                            q.put_nowait(chunk)
                        except asyncio.QueueFull:
                            self.ctx.logger.warning(f"subscriber {q!r} is full, dropping chunk")
                        except Exception as e:
                            self.ctx.logger.exception(f"failed to dispatch chunk to subscriber: {e}")

        finally:

            await stream.release()

            for q in list(self.subscribers):
                try:
                    q.put_nowait(None) # signal end of stream
                except Exception as _:
                    pass


    def stop(self):
        # rarely used, just in case
        self.status = StreamStatus.OFFLINE
        if self.dispatcher:
            self.dispatcher.cancel()