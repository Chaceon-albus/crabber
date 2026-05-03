import json
import logging

from datetime import timedelta
from decimal import Decimal
from typing import Any, Sequence

from crabber.logging import logger as default_logger


def jsonify(obj: dict, indent: int=2, ensure_ascii: bool=False) -> str:
    return json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)


def coin_to_cny(coin: int|float|Decimal, rate: float = 0.001) -> Decimal:
    return Decimal(str(coin)) * Decimal(str(rate))


def format_timedelta(td: timedelta) -> str:

    days = td.days

    hours = td.seconds // 3600
    minutes = (td.seconds // 60) % 60

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分")

    return "".join(parts) if parts else "少于1分钟"


def check_exceptions(results: Sequence[Any], msg: str="error", logger: logging.Logger=default_logger, exc_info: bool=False) -> None:
    for res in results:
        if isinstance(res, Exception):
            logger.error(f"{msg}: {res}", exc_info=res if exc_info else False)


def safe_ts(ts: float | int) -> float:
    return ts if ts < 100_000_000_000 else ts / 1000


def safe_filename(filename: str, fallback: str = "stream_record.flv") -> str:
    illegal_chars = r'/\:*?"<>|' + '\r\n\t'
    table = str.maketrans(illegal_chars, "_" * len(illegal_chars))
    safe_name = filename.translate(table).strip().strip('.')
    return (safe_name[:150] or fallback)


if __name__ == "__main__":
    pass
