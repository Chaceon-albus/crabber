import asyncio
import logging

from datetime import datetime
from typing import List, Optional, Dict, Any

from crabber.database.interface import BaseAdapter
from crabber.database.sqlite import SqliteAdapter
from crabber.database.cloudflare import CloudflareD1Adapter


class Database(BaseAdapter):

    def __init__(self, adapters_config: List[dict], logger: logging.Logger):
        super().__init__(adapters_config, logger)
        self.adapters: List[BaseAdapter] = []
        for ac in adapters_config:
            adapter_type = ac.get("adapter")
            config = ac.get("config", {})
            if adapter_type == "sqlite":
                self.adapters.append(SqliteAdapter(config, self.logger))
            elif adapter_type == "cloudflare":
                self.adapters.append(CloudflareD1Adapter(config, self.logger))
            else:
                self.logger.warning(f"Unknown database adapter type: {adapter_type}")

    def _check_results(self, results: List[Any], task_name: str):
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                adapter_name = self.adapters[i].__class__.__name__
                self.logger.error(f"{adapter_name} failed to {task_name}: {result}")

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, value: float, comment: Optional[str], timestamp: datetime):
        tasks = [
            adapter.record_gift(room_id, user, uid, gift, num, value, comment, timestamp)
            for adapter in self.adapters
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._check_results(results, "record gift")

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime):
        tasks = [
            adapter.record_danmaku(room_id, user, uid, content, timestamp)
            for adapter in self.adapters
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._check_results(results, "record danmaku")

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, offline_gift_revenue: float, offline_guard_revenue: float, offline_sc_revenue: float, gift_revenue: float, guard_revenue: float, sc_revenue: float, summary: str, details: Dict[str, Any]):
        tasks = [
            adapter.record_stats(room_id, title, area, cover_url, start_time, end_time, offline_gift_revenue, offline_guard_revenue, offline_sc_revenue, gift_revenue, guard_revenue, sc_revenue, summary, details) 
            for adapter in self.adapters
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._check_results(results, "record stats")

    async def update_stats(self, room_id: int, start_time: datetime, end_time: datetime, gift_revenue: float, guard_revenue: float, sc_revenue: float, summary: str, details: Dict[str, Any]):
        tasks = [
            adapter.update_stats(room_id, start_time, end_time, gift_revenue, guard_revenue, sc_revenue, summary, details) 
            for adapter in self.adapters
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._check_results(results, "update stats")