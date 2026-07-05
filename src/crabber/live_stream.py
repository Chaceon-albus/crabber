from __future__ import annotations

import aiohttp
import asyncio

from datetime import datetime, timedelta
from enum import Enum
from time import monotonic
from typing import Callable, TYPE_CHECKING
from bilibili_api.live import ScreenResolution


if TYPE_CHECKING:
    from crabber.crabber import Crabber
    from crabber.room_info import RoomInfo


class StreamStatus(Enum):
    OFFLINE = -1
    ONLINE = 0
    STREAMING = 1


class LiveStream:

    def __init__(
        self,
        manager: LiveStreamManager,
        protocol_name: str,
        format_name: str,
        codec_name: str,
        qn: int,
        urls: list[str],
    ) -> None:

        self.manager = manager
        self.protocol_name = protocol_name
        self.format_name = format_name
        self.codec_name = codec_name
        self.qn = qn
        self.urls = urls


    async def download(
        self,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> aiohttp.ClientResponse | None:

        manager = self.manager
        ctx = manager.ctx

        timeout = timeout or aiohttp.ClientTimeout(
            total=None,
            connect=10.0,
            sock_read=30.0, # in case of network issues or cdn hiccups
            sock_connect=10.0
        )

        if not manager.client:
            headers = {
                "Origin": "https://live.bilibili.com",
                "Referer": f"https://live.bilibili.com/{ctx.room_info.id}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                "Connection": "keep-alive",
            }
            manager.client = aiohttp.ClientSession(headers=headers, timeout=timeout)

        for url in self.urls:
            ctx.logger.debug(f"start to download stream: {url}")

            resp = None
            try:
                resp = await manager.client.get(url, timeout=timeout, ssl=False) # some cdn may have invalid ssl certs
                resp.raise_for_status()
            except aiohttp.ClientResponseError as e:
                # when the stream is not ready or accidentally stopped, resp got 404,
                # retry silently in this case instead of throwing many warnings
                if e.status not in [404]:
                    url_str = str(e.request_info.url) if e.request_info and e.request_info.url else "unknown url"
                    url_str = (url_str[:50] + "...") if len(url_str) > 50 else url_str
                    ctx.logger.warning(f"failed to download stream: {e.status} {e.message} ({url_str})")
                if resp is not None: resp.release()
            except Exception as e:
                ctx.logger.warning(f"failed to download stream: {e}")
                if resp is not None: resp.release()
            else:
                return resp

        return None


class LiveStreamManager:

    def __init__(self, ctx: Crabber) -> None:
        self.ctx = ctx

        streaming_handler = self.get_streaming_handler()
        self.ctx.add_streaming_callback(streaming_handler)

        # start OFFLINE until room status events or polling promote the stream lifecycle.
        self.status = StreamStatus.OFFLINE
        self.client: aiohttp.ClientSession | None = None
        self.dispatcher: asyncio.Task | None = None
        self.subscribers: list[asyncio.Queue] = []
        self.current_format: str | None = None
        self._full_subscriber_log_state: dict[int, tuple[float, int]] = {}
        self._restart_requested: str | None = None


    async def get_live_streams(self) -> list[LiveStream]:

        streams = []

        if not self.ctx.room:
            self.ctx.logger.warning(f"LiveRoom not configured")
            return streams

        try:
            resp: dict = await self.ctx.room.get_room_play_info_v2()
        except Exception as e:
            self.ctx.logger.error(f"failed to fetch live streams: {e}")
        else:
            playurl_info = resp.get("playurl_info", {}) or {}
            playurl = playurl_info.get("playurl", {}) or {}
            expected_quality = playurl.get("expected_quality", {}) or {}
            current_qn = expected_quality.get("qn", "unknown")
            g_qn_desc = playurl.get("g_qn_desc", []) or []
            quality_name = _format_screen_resolution(current_qn, g_qn_desc)
            accept_quality = [q.get("qn") for q in g_qn_desc if q and "qn" in q]

            stream_list = playurl.get("stream", []) or []
            for stream_info in stream_list:
                protocol_name = stream_info.get("protocol_name", "")
                for format_info in stream_info.get("format", []) or []:
                    format_name = format_info.get("format_name", "")
                    for codec_info in format_info.get("codec", []) or []:
                        codec_name = codec_info.get("codec_name", "")
                        qn = codec_info.get("current_qn")
                        base_url = codec_info.get("base_url", "")
                        urls = []
                        for url_info in codec_info.get("url_info", []) or []:
                            host = url_info.get("host", "")
                            extra = url_info.get("extra", "")
                            if host and base_url:
                                urls.append(f"{host}{base_url}{extra}")
                        if urls:
                            streams.append(
                                LiveStream(
                                    manager=self,
                                    protocol_name=protocol_name,
                                    format_name=format_name,
                                    codec_name=codec_name,
                                    qn=qn,
                                    urls=urls,
                                )
                            )

            protocols = set(s.protocol_name for s in streams)
            formats = set(s.format_name for s in streams)
            codecs = set(s.codec_name for s in streams)

            self.ctx.logger.info(
                f"live stream quality: {quality_name} ({current_qn}), "
                f"accept_quality={accept_quality}, "
                f"protocols={list(protocols)}, formats={list(formats)}, codecs={list(codecs)}"
            )

        return streams


    async def has_available_stream(self) -> bool:
        stream = None
        try:
            for s in self._preferred_http_streams(await self.get_live_streams()):
                stream = await s.download()
                if stream is not None:
                    return True
        except Exception as e:
            self.ctx.logger.warning(f"failed to probe live stream availability: {e}")
        finally:
            if stream is not None:
                stream.release()

        return False


    @staticmethod
    def _preferred_http_streams(streams: list[LiveStream]) -> list[LiveStream]:
        # filter out HLS streams and sort by format preference (flv > ts > fmp4)
        format_pref = {"flv": 0, "ts": 1, "fmp4": 2}
        http_streams = [s for s in streams if s.protocol_name == "http_stream"]
        http_streams.sort(key=lambda s: format_pref.get(s.format_name, 99))
        return http_streams


    def subscribe(self, q: asyncio.Queue | None = None) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=128) if q is None else q # ~64KB * 128 = 8MB of buffer
        self.subscribers.append(q)
        return q


    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)
        self._full_subscriber_log_state.pop(id(q), None)

        self._signal_subscriber_end(q)


    def get_streaming_handler(self, retry_delay: float = 10.0) -> Callable[[RoomInfo], asyncio._CoroutineLike]:

        ctx = self.ctx

        async def handler(_) -> None:

            if self.dispatcher and not self.dispatcher.done():
                ctx.logger.debug("live stream handler is already running, skipping...")
                return

            async def _dispatch_worker() -> None:

                last_retry_time = datetime.fromtimestamp(0) # never retry before
                failure_counter = 0
                failure_flag = False

                try:
                    # streaming callbacks create this dispatcher; OFFLINE stops retries and dispatch.
                    while self.status != StreamStatus.OFFLINE:

                        if not self.subscribers:
                            await asyncio.sleep(1) # if no subscribers, wait until there is at least one subscriber
                            continue

                        stream = None
                        delay = 0

                        try:

                            if self._restart_requested:
                                ctx.logger.info(f"restarting live stream dispatcher: {self._restart_requested}")
                                self._restart_requested = None

                            # force retry after delay
                            if datetime.now() - last_retry_time < timedelta(seconds=retry_delay):
                                delay = retry_delay - (datetime.now() - last_retry_time).total_seconds()

                            if delay > 0:
                                ctx.logger.info(f"trying to download live stream in {delay:.1f} second(s)")
                                await asyncio.sleep(delay)

                            # any attempt will update the last_retry_time
                            last_retry_time = datetime.now()
                            self.current_format = None

                            if (streams := await self.get_live_streams()):
                                for s in self._preferred_http_streams(streams):
                                    if (stream := await s.download()) is not None:
                                        self.current_format = s.format_name
                                        break

                                if stream is not None:
                                    # reset failure counter & flag on success
                                    failure_counter = 0
                                    failure_flag = False
                                    # start to dispatch the stream
                                    ctx.logger.debug(f"successfully start downloading live stream ({self.current_format}), start dispatching")
                                    await self._dispatch(stream)
                                else:
                                    # failed: no stream
                                    failure_flag = True
                            else:
                                # failed: no stream url
                                failure_flag = True

                            if failure_flag:
                                failure_counter += 1

                        except Exception as e:
                            ctx.logger.error(f"error in live stream handler: {e}")
                        finally:
                            if stream is not None: stream.release()

                finally:
                    self.dispatcher = None


            self.dispatcher = asyncio.create_task(_dispatch_worker())


        handler.__name__ = "[LiveStream]on_live_start"
        return handler


    async def _dispatch(self, stream: aiohttp.ClientResponse) -> None:

        try:
            while True:

                # offline status wins over a readable response so subscribers are ended promptly.
                if self.status == StreamStatus.OFFLINE: break
                if self._restart_requested: break

                if not (subs:= list(self.subscribers)): break

                try:
                    chunk = await stream.content.readany()
                except Exception as e:
                    # when the room goes offline, the stream will be closed and cause a timeout or other read error
                    if self.ctx.room_info.is_online: self.ctx.logger.warning(f"failed to read chunk from stream: {e}")
                    break
                else:
                    if not chunk: break

                    for q in subs:
                        try:
                            q.put_nowait(chunk)
                        except asyncio.QueueFull:
                            self._handle_subscriber_queue_full(q, len(chunk))
                        except Exception as e:
                            self.ctx.logger.error(f"failed to dispatch chunk to subscriber: {e}")

                    if self._restart_requested: break

        finally:

            stream.release()

            # end-of-stream sentinel lets recorder/iris close files and encoders cleanly.
            for q in list(self.subscribers):
                self._signal_subscriber_end(q)


    def stop(self):
        # rarely used, just in case
        # manual shutdown uses the same OFFLINE state that room offline transitions use.
        self.status = StreamStatus.OFFLINE
        if self.dispatcher:
            self.dispatcher.cancel()


    def request_restart(self, reason: str) -> None:
        if self.status == StreamStatus.OFFLINE:
            return
        if not self._restart_requested:
            self._restart_requested = reason


    def _handle_subscriber_queue_full(self, q: asyncio.Queue, chunk_size: int) -> None:
        self._log_subscriber_queue_full(q, chunk_size)
        dropped = self._reset_subscriber_queue(q)
        self.request_restart("subscriber queue is full")
        self.ctx.logger.debug(
            f"reset {self._format_subscriber_queue(q)} after dropping {dropped} queued chunk(s)"
        )


    def _log_subscriber_queue_full(self, q: asyncio.Queue, chunk_size: int) -> None:
        qid = id(q)
        now = monotonic()
        interval = 10.0
        state = self._full_subscriber_log_state.get(qid)

        if state is None:
            self._full_subscriber_log_state[qid] = (now, 0)
            self.ctx.logger.warning(
                f"{self._format_subscriber_queue(q)} is full, dropping chunk ({chunk_size} bytes)"
            )
            return

        last_log, suppressed = state
        if now - last_log < interval:
            self._full_subscriber_log_state[qid] = (last_log, suppressed + 1)
            return

        self._full_subscriber_log_state[qid] = (now, 0)
        suffix = f", suppressed {suppressed} similar drop(s)" if suppressed else ""
        self.ctx.logger.warning(
            f"{self._format_subscriber_queue(q)} is full, dropping chunk ({chunk_size} bytes{suffix})"
        )


    @staticmethod
    def _format_subscriber_queue(q: asyncio.Queue) -> str:
        maxsize = getattr(q, "maxsize", getattr(q, "_maxsize", "unknown"))
        parts = [
            f"type={type(q).__name__}",
            f"id=0x{id(q):x}",
            f"size={q.qsize()}",
            f"maxsize={maxsize}",
        ]
        return f"subscriber queue ({', '.join(parts)})"


    @staticmethod
    def _reset_subscriber_queue(q: asyncio.Queue) -> int:
        dropped = 0
        while True:
            try:
                q.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break

        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass
        return dropped


    def _signal_subscriber_end(self, q: asyncio.Queue) -> None:
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            self._reset_subscriber_queue(q)
        except Exception as e:
            self.ctx.logger.error(f"failed to notify subscriber: {e}")


    async def close(self) -> None:
        self.stop()

        if self.dispatcher:
            await asyncio.gather(self.dispatcher, return_exceptions=True)
            self.dispatcher = None

        if self.client and not self.client.closed:
            await self.client.close()


def _format_screen_resolution(qn: int | str, g_qn_desc: list[dict] | None = None) -> str:
    try:
        qn = int(qn)
    except (TypeError, ValueError):
        return "unknown"

    if g_qn_desc:
        for q in g_qn_desc:
            if isinstance(q, dict) and q.get("qn") == qn:
                if (desc := q.get("desc")):
                    return desc

    for resolution in ScreenResolution:
        if resolution.value == qn:
            return resolution.name

    return "unknown"
