from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from crabber.live_stream import LiveStream


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

    stream: Optional[LiveStream] = None


if __name__ == "__main__":
    pass