import asyncio
import logging

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from crabber.database.interface import BaseAdapter
from crabber.database.records import GiftRecord, DanmakuRecord, LiveRecord


class SqliteAdapter(BaseAdapter):

    def __init__(self, config: dict, logger: logging.Logger):
        super().__init__()
        self.logger = logger
        self.path = config.get("path", "crabberDB.sqlite")
        self._write_lock = asyncio.Lock()
        self._engine = None
        self._initialized = False

    async def _ensure_init(self):
        if self._initialized:
            return

        async with self._write_lock:
            if self._initialized:
                return

            self.logger.debug(f"initializing sqlmodel with {self.path}")
            self._engine = create_async_engine(f"sqlite+aiosqlite:///{self.path}")
            
            async with self._engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
                await self._run_migrations(conn)

            self._initialized = True

    async def record_gift(self, room_id: int, user: str, uid: int, gift: str, num: int, total_value: Decimal, comment: str | None, timestamp: datetime):
        await self._ensure_init()
        async with AsyncSession(self._engine) as session:
            record = GiftRecord(
                room_id=room_id, user=user, uid=uid, gift=gift, num=num,
                total_value=total_value.quantize(Decimal("0.00")),
                comment=comment or "", timestamp=int(timestamp.timestamp())
            )
            session.add(record)
            await session.commit()

    async def record_danmaku(self, room_id: int, user: str, uid: int, content: str, timestamp: datetime, mode: int = 1, color: int = 16777215):
        await self._ensure_init()
        async with AsyncSession(self._engine) as session:
            record = DanmakuRecord(
                room_id=room_id, user=user, uid=uid, content=content,
                timestamp=int(timestamp.timestamp()), mode=mode, color=color
            )
            session.add(record)
            await session.commit()

    async def record_stats(self, room_id: int, title: str, area: str, cover_url: str, start_time: datetime, end_time: datetime, offline_gift_revenue: Decimal, offline_guard_revenue: Decimal, offline_sc_revenue: Decimal, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: dict[str, Any]):
        await self._ensure_init()
        async with AsyncSession(self._engine) as session:
            statement = select(LiveRecord).where(
                LiveRecord.room_id == room_id,
                LiveRecord.start_time == int(start_time.timestamp())
            )
            existing = (await session.exec(statement)).first()
            if not existing:
                record = LiveRecord(
                    room_id=room_id, title=title, area=area, cover_url=cover_url,
                    start_time=int(start_time.timestamp()), end_time=int(end_time.timestamp()),
                    offline_gift_revenue=offline_gift_revenue.quantize(Decimal("0.00")),
                    offline_guard_revenue=offline_guard_revenue.quantize(Decimal("0.00")),
                    offline_sc_revenue=offline_sc_revenue.quantize(Decimal("0.00")),
                    gift_revenue=gift_revenue.quantize(Decimal("0.00")),
                    guard_revenue=guard_revenue.quantize(Decimal("0.00")),
                    sc_revenue=sc_revenue.quantize(Decimal("0.00")),
                    summary=summary, details=details
                )
                session.add(record)
                await session.commit()

    async def update_stats(self, room_id: int, start_time: datetime, end_time: datetime, gift_revenue: Decimal, guard_revenue: Decimal, sc_revenue: Decimal, summary: str, details: dict[str, Any]):
        await self._ensure_init()
        async with AsyncSession(self._engine) as session:
            statement = select(LiveRecord).where(
                LiveRecord.room_id == room_id,
                LiveRecord.start_time == int(start_time.timestamp())
            )
            record = (await session.exec(statement)).first()
            if record:
                record.end_time = int(end_time.timestamp())
                record.gift_revenue = gift_revenue.quantize(Decimal("0.00"))
                record.guard_revenue = guard_revenue.quantize(Decimal("0.00"))
                record.sc_revenue = sc_revenue.quantize(Decimal("0.00"))
                record.summary = summary
                record.details = details
                session.add(record)
                await session.commit()

    async def get_latest_live_record(self, room_id: int) -> dict[str, Any] | None:
        await self._ensure_init()
        async with AsyncSession(self._engine) as session:
            statement = select(LiveRecord).where(LiveRecord.room_id == room_id).order_by(LiveRecord.start_time.desc()).limit(1)
            record = (await session.exec(statement)).first()
            if record:
                return {
                    "room_id": record.room_id,
                    "start_time": datetime.fromtimestamp(record.start_time),
                    "end_time": datetime.fromtimestamp(record.end_time),
                }
        return None

    async def get_gift_summary(self, room_id: int, start_timestamp: datetime) -> dict[str, Decimal]:
        await self._ensure_init()
        async with AsyncSession(self._engine) as session:
            statement = select(GiftRecord.gift, GiftRecord.total_value).where(
                GiftRecord.room_id == room_id,
                GiftRecord.timestamp >= int(start_timestamp.timestamp())
            )
            results = (await session.exec(statement)).all()
            
            summary = {
                "gift_revenue": Decimal("0.00"),
                "guard_revenue": Decimal("0.00"),
                "sc_revenue": Decimal("0.00")
            }
            for gift, total_value in results:
                val = Decimal(total_value)
                if gift == "SuperChat":
                    summary["sc_revenue"] += val
                elif gift in ["舰长", "提督", "总督"]:
                    summary["guard_revenue"] += val
                else:
                    summary["gift_revenue"] += val
            
            return summary

    async def _run_migrations(self, conn):
        """
        Run database migrations programmatically using SQLAlchemy Inspector.
        """
        def get_columns(sync_conn, table_name: str):
            inspector = inspect(sync_conn)
            if inspector.has_table(table_name):
                return [col["name"] for col in inspector.get_columns(table_name)]
            return []

        # 2026-05-04: Added `mode` and `color` columns to `danmaku_record`.
        danmaku_cols = await conn.run_sync(get_columns, "danmaku_record")
        if danmaku_cols:
            if "mode" not in danmaku_cols:
                await conn.execute(text("ALTER TABLE danmaku_record ADD COLUMN mode INT DEFAULT 1;"))
            if "color" not in danmaku_cols:
                await conn.execute(text("ALTER TABLE danmaku_record ADD COLUMN color INT DEFAULT 16777215;"))
