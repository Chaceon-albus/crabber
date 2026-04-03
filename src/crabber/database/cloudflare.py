import asyncio
import json
import logging
import warnings

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

# Suppress Pydantic V1 compatibility warning from cloudflare SDK
warnings.filterwarnings("ignore", message=".*Core Pydantic V1 functionality.*")
from cloudflare import AsyncCloudflare

from crabber.database.interface import BaseAdapter


class CloudflareD1Adapter(BaseAdapter):

    def __init__(self, config: dict, logger: logging.Logger):
        super().__init__()

        self.logger = logger

        self.account_id = config.get("account_id", "")
        self.api_token  = config.get("api_token", "")
        self.dataset_id = config.get("dataset_id", "")

        if not all([self.account_id, self.api_token, self.dataset_id]):
            raise ValueError("Cloudflare D1 configuration is incomplete. Please provide account_id, api_token, and dataset_id.")

        # Initialize the official async cloudflare client
        self.client = AsyncCloudflare(api_token=self.api_token)
        self._write_lock = asyncio.Lock()

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, total_value: Decimal, comment: Optional[str], timestamp: datetime):
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

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, offline_gift_revenue: Decimal, offline_guard_revenue: Decimal, offline_sc_revenue: Decimal, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: Dict[str, Any]):
        details_str = json.dumps(details)
        sql = """
            INSERT INTO live_record
            (room_id, title, area, cover_url, start_time, end_time, offline_gift_revenue, offline_guard_revenue, offline_sc_revenue, gift_revenue, guard_revenue, sc_revenue, summary, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = [room_id, title, area, cover_url, int(start_time.timestamp()), int(end_time.timestamp()), f"{offline_gift_revenue:.2f}", f"{offline_guard_revenue:.2f}", f"{offline_sc_revenue:.2f}", f"{gift_revenue:.2f}", f"{guard_revenue:.2f}", f"{sc_revenue:.2f}", summary, details_str]

        async with self._write_lock:
            await self._execute_sql(sql, params)

    async def update_stats(self, room_id: int, start_time: datetime, end_time: datetime, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: Dict[str, Any]):
        details_str = json.dumps(details)
        sql = """
            UPDATE live_record
            SET end_time=?, gift_revenue=?, guard_revenue=?, sc_revenue=?, summary=?, details=?
            WHERE room_id=? AND start_time=?
        """
        params = [int(end_time.timestamp()), f"{gift_revenue:.2f}", f"{guard_revenue:.2f}", f"{sc_revenue:.2f}", summary, details_str, room_id, int(start_time.timestamp())]

        async with self._write_lock:
            await self._execute_sql(sql, params)
