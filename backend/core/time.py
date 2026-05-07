from zoneinfo import ZoneInfo
from datetime import datetime, timezone

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def now_vn() -> datetime:
    """Logic, log, filter '24h qua'. KHÔNG lưu DB."""
    return datetime.now(VN_TZ)


def now_utc() -> datetime:
    """Lưu DB. KHÔNG dùng datetime.utcnow() (deprecated)."""
    return datetime.now(timezone.utc)


def to_vn(dt: datetime) -> datetime:
    return dt.astimezone(VN_TZ)


def format_vn(dt: datetime) -> str:
    """Format log: DD/MM/YYYY HH:mm"""
    return to_vn(dt).strftime("%d/%m/%Y %H:%M")
