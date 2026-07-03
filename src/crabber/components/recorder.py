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
WRITE_TIMEOUT = 30.0


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
        output_path: Path | None = None
        awaiting_fresh_stream = False

        if ffmpeg_path:=shutil.which("ffmpeg"):
            # use ffmpeg to write .mp4 file
            ffmpeg: FFmpegProcess | None = None

            while True:
                try:
                    data: bytes | None = await queue.get()

                    if data is None:
                        awaiting_fresh_stream = False
                        if ffmpeg is not None:
                            logger.info(f"stop recording: {output_path}")
                            await _close_ffmpeg(ffmpeg, logger)
                            ffmpeg = None
                        continue

                    if awaiting_fresh_stream:
                        continue

                    if ffmpeg is None or not ffmpeg.is_running:
                        if ffmpeg is not None:
                            await _close_ffmpeg(ffmpeg, logger)
                        # get dest filename
                        output_path = _build_output_path(output_dir, template, ctx, ".mp4")

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
                                str(output_path.resolve()),
                            ],
                            ffmpeg_path=ffmpeg_path,
                            logger=logger,
                        )
                        await ffmpeg.start()
                        logger.info(f"start recording: {output_path}")

                    await asyncio.wait_for(ffmpeg.write(data), timeout=WRITE_TIMEOUT)

                except asyncio.CancelledError:
                    logger.info("recorder task cancelled")
                    if ffmpeg is not None:
                        await _close_ffmpeg(ffmpeg, logger)
                        ffmpeg = None
                    return

                except Exception as e:
                    logger.exception(f"recorder error, waiting for a fresh stream before resuming: {e}")
                    if ffmpeg is not None:
                        await _close_ffmpeg(ffmpeg, logger)
                        ffmpeg = None
                    await _cleanup_empty_file(output_path, logger)
                    _request_fresh_stream(ctx, f"recorder write failed: {type(e).__name__}")
                    awaiting_fresh_stream = True

        else:
            # directly write to .flv file
            fp: AsyncBufferedIOBase | None = None
            while True:
                try:
                    data: bytes | None = await queue.get()

                    if data is None: # end of stream
                        awaiting_fresh_stream = False
                        if fp is not None and not fp.closed:
                            logger.info(f"stop recording: {fp.name}")
                            await _close_file(fp, logger)
                            fp = None
                        continue

                    if awaiting_fresh_stream:
                        continue

                    if fp is None or fp.closed:
                        output_path = _build_output_path(output_dir, template, ctx, ".flv")
                        fp = await aiofiles.open(output_path, mode="wb")
                        logger.info(f"start recording: {fp.name}")

                    await asyncio.wait_for(fp.write(data), timeout=WRITE_TIMEOUT)

                except asyncio.CancelledError:
                    logger.info("recorder task cancelled")
                    if fp is not None:
                        await _close_file(fp, logger)
                    return
                except Exception as e:
                    logger.exception(f"recorder error, waiting for a fresh stream before resuming: {e}")
                    if fp is not None:
                        await _close_file(fp, logger)
                        fp = None
                    await _cleanup_empty_file(output_path, logger)
                    _request_fresh_stream(ctx, f"recorder write failed: {type(e).__name__}")
                    awaiting_fresh_stream = True


    ctx.add_task(_recorder())


    return empty_handler


def _build_output_path(output_dir: Path, template: str, ctx: Crabber, ext: str) -> Path:
    tmpl = Template(template)
    generated_name = tmpl.safe_substitute({
        "date": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        "room_id": ctx.room_info.id,
        "title": ctx.room_info.title,
    })
    return _ensure_ext(output_dir.joinpath(safe_filename(generated_name)), ext)


async def _close_ffmpeg(ffmpeg: FFmpegProcess, logger) -> None:
    try:
        await ffmpeg.close()
    except Exception as e:
        logger.warning(f"failed to close ffmpeg after recorder error: {e}")


async def _close_file(fp: AsyncBufferedIOBase, logger) -> None:
    try:
        await fp.close()
    except Exception as e:
        logger.warning(f"failed to close recording file after recorder error: {e}")


async def _cleanup_empty_file(fn: Path | str | None, logger) -> None:
    if fn is None:
        return

    path = Path(fn)
    try:
        if path.exists() and path.is_file() and path.stat().st_size == 0:
            path.unlink()
            logger.info(f"removed empty recording file after recorder error: {path}")
    except Exception as e:
        logger.warning(f"failed to remove empty recording file {path}: {e}")


def _request_fresh_stream(ctx: Crabber, reason: str) -> None:
    stream = ctx.room_info.stream
    if stream is not None:
        stream.request_restart(reason)


def _ensure_ext(fn: Path, ext: str) -> Path:
    target_ext = ext if ext.startswith(".") else f".{ext}"
    return fn.with_suffix(target_ext) if fn.suffix.lower() != target_ext.lower() else fn
