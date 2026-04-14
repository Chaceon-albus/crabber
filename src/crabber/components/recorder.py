import asyncio

import aiofiles

from datetime import datetime
from pathlib import Path
from string import Template
from typing import Callable, Awaitable, Optional

from aiofiles.threadpool.binary import AsyncBufferedIOBase

from crabber.crabber import Crabber
from crabber.misc import safe_filename
from crabber.components import empty_handler


default_events = []


def get_handler(ctx: Crabber, path: str, template: str = "", *args, **kwargs) -> Callable[[dict], Awaitable[None]]:

    logger = ctx.logger
    template = template if template else "{date}_{room_id}_{title}.flv"

    output_dir = Path(path)
    if not output_dir.exists() or not output_dir.is_dir():
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"create output directory: {output_dir.resolve()}")


    async def _recorder() -> None:
        # Create the queue inside the coroutine so it's bound to the running event loop
        queue = asyncio.Queue(maxsize=128)
        ctx.room_info.stream.subscribe(queue)  # type: ignore

        fp: Optional[AsyncBufferedIOBase] = None
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
                        fp = await aiofiles.open(fn, mode="wb")
                        logger.info(f"start recording: {fp.name}")

                await fp.write(data)

            except asyncio.CancelledError:
                logger.info("recorder task cancelled")
                if fp is not None: await fp.close()
                fp = None
            except Exception as e:
                logger.error(f"recorder error: {e}")
                if fp is not None: await fp.close()
                fp = None


    ctx.add_task(_recorder())


    return empty_handler