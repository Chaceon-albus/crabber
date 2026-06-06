from datetime import datetime
from decimal import Decimal
from typing import Dict, Any


class BaseAdapter:

    def __init__(self):
        pass

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, total_value: Decimal, comment: str | None, timestamp: datetime):
        pass

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime, mode: int = 1, color: int = 16777215):
        pass

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, offline_gift_revenue: Decimal, offline_guard_revenue: Decimal, offline_sc_revenue: Decimal, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: Dict[str, Any]):
        pass

    async def update_stats(self, room_id: int, start_time: datetime, end_time: datetime, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: Dict[str, Any]):
        pass

    async def get_latest_live_record(self, room_id: int) -> Dict[str, Any] | None:
        pass

    async def get_gift_summary(self, room_id: int, start_timestamp: datetime) -> Dict[str, Decimal] | None:
        pass
