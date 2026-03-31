import asyncio
import logging

from datetime import datetime
from typing import Optional, Dict, Any

from tortoise import Tortoise

from crabber.database.interface import BaseAdapter
from crabber.database.records import GiftRecord, DanmakuRecord, LiveRecord


class SqliteAdapter(BaseAdapter):

    def __init__(self, config: dict, logger: logging.Logger):
        super().__init__(config, logger)
        self.path = config.get("path", "crabberDB.sqlite")
        self._write_lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_init(self):
        if self._initialized:
            return

        async with self._write_lock:
            if self._initialized:
                return

            if not Tortoise._inited:
                self.logger.debug(f"initializing tortoise with {self.path}")
                await Tortoise.init(
                    db_url=f'sqlite://{self.path}',
                    modules={'models': ['crabber.database.records']}
                )
                await Tortoise.generate_schemas(safe=True)
            else:
                self.logger.debug("tortoise already initialized, skipping init")

            self._initialized = True

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, value: float, comment: Optional[str], timestamp: datetime):
        await self._ensure_init()
        async with self._write_lock:
            await GiftRecord.create(
                room_id=room_id, user=user, uid=uid, gift=gift, num=num, value=value, comment=comment, timestamp=int(timestamp.timestamp())
            )

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime):
        await self._ensure_init()
        async with self._write_lock:
            await DanmakuRecord.create(
                room_id=room_id, user=user, uid=uid, content=content, timestamp=int(timestamp.timestamp())
            )

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, gift_revenue: float, guard_revenue: float, sc_revenue: float, summary: str, details: Dict[str, Any]):
        await self._ensure_init()
        async with self._write_lock:
            await LiveRecord.create(
                room_id=room_id, title=title, area=area, cover_url=cover_url,
                start_time=int(start_time.timestamp()), end_time=int(end_time.timestamp()),
                gift_revenue=gift_revenue, guard_revenue=guard_revenue, sc_revenue=sc_revenue,
                summary=summary, details=details
            )
