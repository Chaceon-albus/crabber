import asyncio

from typing import Callable

from crabber.logging import logger


def create_safe_handler(handler_func: Callable, crabber_name: str, cmp_name: str) -> Callable:

    async def wrapped_handler(*args, **kwargs):
        try:
            result = handler_func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result

        except Exception as e:
            logger.error(
                f"{cmp_name} in {crabber_name} failed: {e}",
                exc_info=True,
            )

    return wrapped_handler