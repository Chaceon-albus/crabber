import asyncio
import shutil

import aiofiles

from contextlib import suppress
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Callable, Awaitable

from aiofiles.threadpool.binary import AsyncBufferedIOBase

from crabber.crabber import Crabber
from crabber.misc import safe_filename
from crabber.components import empty_handler


default_events = []


def get_handler(ctx: Crabber, path: str, template: str = "", *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger
    template = template if template else "${date}_${room_id}_${title}.flv"

    output_dir = Path(path)
    if not output_dir.exists() or not output_dir.is_dir():
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"create output directory: {output_dir.resolve()}")


    async def _recorder() -> None:
        # Create the queue inside the coroutine so it's bound to the running event loop
        queue = asyncio.Queue(maxsize=128)
        ctx.room_info.stream.subscribe(queue)  # type: ignore

        if ffmpeg_path:=shutil.which("ffmpeg"):
            # use ffmpeg to write .mp4 file
            fn: Path | str | None = None
            ffmpeg_stdin: asyncio.StreamWriter | None = None
            ffmpeg_process: asyncio.subprocess.Process | None = None

            while True:
                try:
                    data: bytes | None = await queue.get()

                    if data is None:
                        if ffmpeg_process is not None or ffmpeg_stdin is not None:
                            logger.info(f"stop recording: {fn}")
                            await _gracefully_close_ffmpeg(ffmpeg_process, ffmpeg_stdin)
                            ffmpeg_process = None
                            ffmpeg_stdin = None
                    else:
                        if ffmpeg_stdin is None or ffmpeg_stdin.is_closing():
                            # get dest filename
                            tmpl = Template(template)
                            fn = tmpl.safe_substitute({
                                "date": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                                "room_id": ctx.room_info.id,
                                "title": ctx.room_info.title,
                            })
                            fn = output_dir.joinpath(safe_filename(fn))
                            fn = _ensure_ext(fn, ".mp4")

                            ffmpeg_process = await asyncio.create_subprocess_exec(
                                ffmpeg_path, "-nostdin", "-y",
                                "-i", "pipe:0", "-c", "copy",
                                "-movflags", "empty_moov+default_base_moof+frag_keyframe",
                                fn.resolve(),
                                stdin=asyncio.subprocess.PIPE,
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                            )
                            ffmpeg_stdin = ffmpeg_process.stdin
                            logger.info(f"start recording: {fn}")

                        if ffmpeg_stdin is None:
                            raise RuntimeError("failed to open ffmpeg stdin")

                        ffmpeg_stdin.write(data)
                        await ffmpeg_stdin.drain()

                except asyncio.CancelledError:
                    logger.info("recorder task cancelled")
                    await _gracefully_close_ffmpeg(ffmpeg_process, ffmpeg_stdin)
                    ffmpeg_process = None
                    ffmpeg_stdin = None
                    return

                except Exception as e:
                    logger.error(f"recorder error: {e}")
                    await _gracefully_close_ffmpeg(ffmpeg_process, ffmpeg_stdin)
                    ffmpeg_process = None
                    ffmpeg_stdin = None

        else:
            # directly write to .flv file
            fp: AsyncBufferedIOBase | None = None
            while True:
                try:
                    data: bytes | None = await queue.get()

                    if data is None: # end of stream
                        if fp is not None and not fp.closed:
                            logger.info(f"stop recording: {fp.name}")
                            await fp.close()
                            fp = None
                        continue
                    else:
                        if fp is None or fp.closed:
                            tmpl = Template(template)
                            fn = tmpl.safe_substitute({
                                "date": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                                "room_id": ctx.room_info.id,
                                "title": ctx.room_info.title,
                            })
                            fn = output_dir.joinpath(safe_filename(fn))
                            fp = await aiofiles.open(_ensure_ext(fn, ".flv"), mode="wb")
                            logger.info(f"start recording: {fp.name}")

                    await fp.write(data)

                except asyncio.CancelledError:
                    logger.info("recorder task cancelled")
                    if fp is not None: await fp.close()
                    return
                except Exception as e:
                    logger.error(f"recorder error: {e}")
                    if fp is not None: await fp.close()
                    fp = None


    ctx.add_task(_recorder())


    return empty_handler


def _ensure_ext(fn: Path, ext: str) -> Path:
    target_ext = ext if ext.startswith(".") else f".{ext}"
    return fn.with_suffix(target_ext) if fn.suffix.lower() != target_ext.lower() else fn


async def _gracefully_close_ffmpeg(
    process: asyncio.subprocess.Process | None,
    stdin: asyncio.StreamWriter | None,
    timeout: float = 10.0,
) -> None:

    if stdin is not None:
        with suppress(BrokenPipeError, ConnectionResetError, OSError, RuntimeError):
            if stdin.can_write_eof():
                stdin.write_eof()

    if process:
        if stdin and not stdin.is_closing():
            with suppress(BrokenPipeError, ConnectionResetError, OSError, RuntimeError):
                stdin.close()
                await stdin.wait_closed()

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5.0)
