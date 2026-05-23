from typing import Callable, Awaitable

from crabber.crabber import Crabber
from crabber.components import empty_handler


default_events = []


def get_handler(ctx: Crabber, *args, **kwargs) -> Callable[[dict], Awaitable[None]]:
    return empty_handler
