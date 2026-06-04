from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from crabber.live_stream import LiveStreamManager


@dataclass
class RoomInfo:

    id: int
    area: str = ""
    uname: str = ""
    title: str = ""
    cover: str = ""
    is_online: bool = False
    start_time: datetime = datetime.now()
    end_time: datetime = datetime.now()

    stream: LiveStreamManager | None = None


if __name__ == "__main__":
    pass
