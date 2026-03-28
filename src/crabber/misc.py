import json

from datetime import timedelta


def jsonify(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def coin_to_cny(coin: int|float, rate: float = 0.001) -> float:
    return coin * rate



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


if __name__ == "__main__":
    pass