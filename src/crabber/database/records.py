from decimal import Decimal
from typing import Any

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, Numeric


class GiftRecord(SQLModel, table=True):
    __tablename__ = "gift_record"
    
    id: int | None = Field(default=None, primary_key=True)
    room_id: int
    user: str = Field(max_length=255)
    uid: int = Field(default=-1)
    gift: str = Field(max_length=255)
    num: int
    total_value: Decimal = Field(sa_column=Column(Numeric(12, 2, asdecimal=True)))
    comment: str = Field(max_length=1024, default="")
    timestamp: int


class DanmakuRecord(SQLModel, table=True):
    __tablename__ = "danmaku_record"
    
    id: int | None = Field(default=None, primary_key=True)
    room_id: int
    user: str = Field(max_length=255)
    uid: int = Field(default=-1)
    content: str = Field(max_length=1024)
    timestamp: int
    mode: int = Field(default=1)
    color: int = Field(default=16777215)


class LiveRecord(SQLModel, table=True):
    __tablename__ = "live_record"
    
    id: int | None = Field(default=None, primary_key=True)
    room_id: int
    title: str = Field(max_length=255)
    area: str = Field(max_length=255)
    cover_url: str = Field(max_length=1024)
    start_time: int
    end_time: int
    offline_gift_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(12, 2, asdecimal=True)))
    offline_guard_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(12, 2, asdecimal=True)))
    offline_sc_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(12, 2, asdecimal=True)))
    gift_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(12, 2, asdecimal=True)))
    guard_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(12, 2, asdecimal=True)))
    sc_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(12, 2, asdecimal=True)))
    summary: str = Field(default="")
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
