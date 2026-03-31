import asyncio
import json
import logging

from datetime import datetime
from typing import Optional, Dict, Any

from cloudflare import AsyncCloudflare

from crabber.database.interface import BaseAdapter


class CloudflareD1Adapter(BaseAdapter):

    def __init__(self, config: dict, logger: logging.Logger):
        super().__init__(config, logger)
        self.account_id = config.get("account_id")
        self.api_token = config.get("api_token")
        self.dataset_id = config.get("dataset_id")

        # Initialize the official async cloudflare client
        self.client = AsyncCloudflare(api_token=self.api_token)
        self._write_lock = asyncio.Lock()

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, value: float, comment: Optional[str], timestamp: datetime):
        pass  # As requested, skip saving detailed gift records to D1

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime):
        pass  # As requested, skip saving detailed danmaku records to D1

    async def _execute_sql(self, sql: str, params: list):
        try:
            return await self.client.d1.database.query(
                database_id=self.dataset_id,
                account_id=self.account_id,
                sql=sql,
                params=params
            )
        except Exception as e:
            self.logger.error(f"Failed to execute D1 SQL: {e}")

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, gift_revenue: float, guard_revenue: float, sc_revenue: float, summary: str, details: Dict[str, Any]):
        details_str = json.dumps(details)
        sql = """
            INSERT INTO live_record
            (room_id, title, area, cover_url, start_time, end_time, gift_revenue, guard_revenue, sc_revenue, summary, details) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = [room_id, title, area, cover_url, int(start_time.timestamp()), int(end_time.timestamp()), gift_revenue, guard_revenue, sc_revenue, summary, details_str]

        async with self._write_lock:
            await self._execute_sql(sql, params)
