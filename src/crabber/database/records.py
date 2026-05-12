from decimal import Decimal
from typing import Any

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, String
import sqlalchemy.types as types


# Length 40 is used to match Tortoise ORM's default VARCHAR length for DecimalField.
# This ensures seamless schema compatibility with existing databases and future migrations.
TORTOISE_DECIMAL_LENGTH = 40


class StringDecimal(types.TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return Decimal(str(value))
        
        # db record is NOT NULL, fallback to 0.00 just in case
        return Decimal("0.00")


class GiftRecord(SQLModel, table=True):
    __tablename__ = "gift_record"
    
    id: int | None = Field(default=None, primary_key=True)
    room_id: int
    user: str = Field(max_length=255)
    uid: int = Field(default=-1)
    gift: str = Field(max_length=255)
    num: int
    total_value: Decimal = Field(sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
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
    offline_gift_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
    offline_guard_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
    offline_sc_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
    gift_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
    guard_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
    sc_revenue: Decimal = Field(default=Decimal(0), sa_column=Column(StringDecimal(TORTOISE_DECIMAL_LENGTH)))
    summary: str = Field(default="")
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
