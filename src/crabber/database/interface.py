from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any


class BaseAdapter:

    def __init__(self):
        pass

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, value: Decimal, comment: Optional[str], timestamp: datetime):
        pass

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime):
        pass

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, offline_gift_revenue: Decimal, offline_guard_revenue: Decimal, offline_sc_revenue: Decimal, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: Dict[str, Any]):
        pass

    async def update_stats(self, room_id: int, start_time: datetime, end_time: datetime, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: Dict[str, Any]):
        pass
