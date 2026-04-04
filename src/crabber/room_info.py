from dataclasses import dataclass
from datetime import datetime


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


if __name__ == "__main__":
    pass