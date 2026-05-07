import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.db import AsyncSessionLocal
from core.time import now_utc
from models.database import MacroEvent

log = logging.getLogger(__name__)


def _parse_event_date(date_str: str, time_str: str = ""):
    """Convert 'YYYY-MM-DD' (+ 'HH:mm' tùy chọn) → datetime UTC aware.
    FRED trả ISO-8601 date chuẩn → stdlib đủ, không cần pandas."""
    if not date_str:
        return None
    try:
        combined = f"{date_str} {time_str}".strip() if time_str else date_str
        # fromisoformat chấp nhận "YYYY-MM-DD" và "YYYY-MM-DD HH:MM".
        dt = datetime.fromisoformat(combined)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def upsert_events(events: list[dict]) -> int:
    """Upsert theo ID stable (sha1 trong `make_event_id`) — quy tắc 8.
    Cùng (event, date, currency) → cùng ID → DO UPDATE để refresh actual."""
    if not events:
        return 0

    now = now_utc()
    rows = []
    for e in events:
        try:
            event_date = _parse_event_date(
                e.get("date", ""), e.get("time", "")
            )
            score = float(e.get("score", 5.0))
            label = e.get("label") or (
                "positive" if score >= 6 else "negative" if score <= 4 else "neutral"
            )
            rows.append(
                {
                    "id": e["id"],
                    "event_name": e.get("event", ""),
                    "event_date": event_date,
                    "currency": e.get("currency", "USD"),
                    "impact": e.get("impact", "High"),
                    "actual": e.get("actual") or None,
                    "forecast": e.get("forecast") or None,
                    "previous": e.get("previous") or None,
                    "sentiment_score": score,
                    "sentiment_label": label,
                    "scraped_at": now,
                }
            )
        except Exception as ex:
            log.warning(f"upsert_events bỏ qua event lỗi: {ex}")

    if not rows:
        return 0

    stmt = sqlite_insert(MacroEvent).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MacroEvent.id],
        set_={
            "event_name": stmt.excluded.event_name,
            "event_date": stmt.excluded.event_date,
            "currency": stmt.excluded.currency,
            "impact": stmt.excluded.impact,
            "actual": stmt.excluded.actual,
            "forecast": stmt.excluded.forecast,
            "previous": stmt.excluded.previous,
            "sentiment_score": stmt.excluded.sentiment_score,
            "sentiment_label": stmt.excluded.sentiment_label,
            "scraped_at": stmt.excluded.scraped_at,
        },
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()
    return len(rows)


async def get_recent_events(days: int = 7) -> list[dict]:
    """Trả events đã scrape trong N ngày gần đây — format giống cache memory."""
    cutoff = now_utc() - timedelta(days=days)
    stmt = (
        select(MacroEvent)
        .where(MacroEvent.scraped_at >= cutoff)
        .order_by(MacroEvent.event_date.desc())
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return [
        {
            "id": r.id,
            "event": r.event_name,
            "date": r.event_date.isoformat() if r.event_date else "",
            "time": "",
            "currency": r.currency,
            "impact": r.impact,
            "actual": r.actual or "",
            "forecast": r.forecast or "",
            "previous": r.previous or "",
            "score": r.sentiment_score,
            "label": r.sentiment_label,
        }
        for r in rows
    ]
