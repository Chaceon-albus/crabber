import asyncio
import shutil

import aiofiles

from datetime import datetime
from pathlib import Path
from string import Template
from typing import Callable, Awaitable

from aiofiles.threadpool.binary import AsyncBufferedIOBase

from crabber.crabber import Crabber
from crabber.misc import safe_filename
from crabber.components import empty_handler
from crabber.ffmpeg import FFmpegProcess


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
            ffmpeg: FFmpegProcess | None = None

            while True:
                try:
                    data: bytes | None = await queue.get()

                    if data is None:
                        if ffmpeg is not None:
                            logger.info(f"stop recording: {fn}")
                            await ffmpeg.close()
                            ffmpeg = None
                    else:
                        if ffmpeg is None or not ffmpeg.is_running:
                            if ffmpeg is not None:
                                await ffmpeg.close()
                            # get dest filename
                            tmpl = Template(template)
                            fn = tmpl.safe_substitute({
                                "date": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                                "room_id": ctx.room_info.id,
                                "title": ctx.room_info.title,
                            })
                            fn = output_dir.joinpath(safe_filename(fn))
                            fn = _ensure_ext(fn, ".mp4")

                            input_args = ["-i", "pipe:0"]

                            if ctx.room_info.stream is not None and ctx.room_info.stream.current_format:
                                fmt = ctx.room_info.stream.current_format
                                if fmt == "flv":
                                    input_args = ["-f", "flv", "-i", "pipe:0"]
                                elif fmt == "ts":
                                    input_args = ["-f", "mpegts", "-i", "pipe:0"]
                                elif fmt == "fmp4":
                                    input_args = ["-f", "mov", "-i", "pipe:0"]

                            ffmpeg = FFmpegProcess(
                                args=[
                                    "-hide_banner",
                                    "-nostdin", "-y",
                                    *input_args, # may get different input type
                                    "-c", "copy",
                                    "-movflags", "empty_moov+default_base_moof+frag_keyframe",
                                    str(fn.resolve()),
                                ],
                                ffmpeg_path=ffmpeg_path,
                                logger=logger,
                            )
                            await ffmpeg.start()
                            logger.info(f"start recording: {fn}")

                        await ffmpeg.write(data)

                except asyncio.CancelledError:
                    logger.info("recorder task cancelled")
                    if ffmpeg is not None:
                        await ffmpeg.close()
                        ffmpeg = None
                    return

                except Exception as e:
                    logger.error(f"recorder error: {e}")
                    if ffmpeg is not None:
                        await ffmpeg.close()
                        ffmpeg = None

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
