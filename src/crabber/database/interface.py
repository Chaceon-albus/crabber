import logging

from datetime import datetime
from typing import Optional, Dict, Any


class BaseAdapter:

    def __init__(self, config: dict, logger: logging.Logger):
        self.logger = logger
        self.config = config

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, value: float, comment: Optional[str], timestamp: datetime):
        pass

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime):
        pass

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, offline_gift_revenue: float, offline_guard_revenue: float, offline_sc_revenue: float, gift_revenue: float, guard_revenue: float, sc_revenue: float, summary: str, details: Dict[str, Any]):
        pass

    async def update_stats(self, room_id: int, start_time: datetime, end_time: datetime, gift_revenue: float, guard_revenue: float, sc_revenue: float, summary: str, details: Dict[str, Any]):
        pass
