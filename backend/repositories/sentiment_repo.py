import logging
from datetime import timedelta

from sqlalchemy import func, select

from core.db import AsyncSessionLocal
from core.time import now_utc
from models.database import SentimentScore

log = logging.getLogger(__name__)


async def last_label(coin_id: str) -> str | None:
    """Trả label của snapshot gần nhất — dùng để diff trước khi gọi
    Gemini `generate_coin_summary` (quy tắc 11)."""
    stmt = (
        select(SentimentScore.label)
        .where(SentimentScore.coin_id == coin_id)
        .order_by(SentimentScore.calculated_at.desc())
        .limit(1)
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def last_snapshot(coin_id: str) -> SentimentScore | None:
    stmt = (
        select(SentimentScore)
        .where(SentimentScore.coin_id == coin_id)
        .order_by(SentimentScore.calculated_at.desc())
        .limit(1)
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def insert_snapshot(
    coin_id: str,
    scores: dict,
    total: float,
    label: str,
    summary: str | None,
    calculated_at,
    social_mentions: int | None = None,
) -> int:
    """Insert 1 snapshot điểm (time-series). `sentiment_scores` dùng
    autoincrement id + composite index `ix_sentiment_coin_time`."""
    def _f(v):
        # None → NULL (cột nullable). Số → float. Tránh float(None) crash.
        return None if v is None else float(v)

    row = SentimentScore(
        coin_id=coin_id,
        score_total=float(total or 0.0),
        score_news=_f(scores.get("news")),
        score_macro=_f(scores.get("macro")),
        score_social=_f(scores.get("social")),
        social_mentions=(
            int(social_mentions) if social_mentions is not None else None
        ),
        score_sentiment=_f(scores.get("sentiment")),
        label=label,
        summary=summary,
        calculated_at=calculated_at,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        return row.id


# Alias cho ngữ cảnh API phase2 — ý nghĩa: ghi snapshot mới nhất.
upsert = insert_snapshot


async def last_snapshots_bulk(
    coin_ids: list[str],
) -> dict[str, SentimentScore]:
    """Trả {coin_id: SentimentScore} cho tất cả coin trong 1 query duy nhất.

    Dùng subquery GROUP BY để lấy max(calculated_at) per coin, sau đó JOIN
    về bảng chính — thay thế N lần gọi last_snapshot() trong vòng lặp.
    """
    if not coin_ids:
        return {}

    sub = (
        select(
            SentimentScore.coin_id,
            func.max(SentimentScore.calculated_at).label("max_at"),
        )
        .where(SentimentScore.coin_id.in_(coin_ids))
        .group_by(SentimentScore.coin_id)
        .subquery()
    )

    stmt = select(SentimentScore).join(
        sub,
        (SentimentScore.coin_id == sub.c.coin_id)
        & (SentimentScore.calculated_at == sub.c.max_at),
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return {row.coin_id: row for row in rows}


async def get_history(
    coin_id: str,
    hours: int = 72,
    limit: int = 100,
) -> list[SentimentScore]:
    """Trả list snapshot theo thứ tự tăng dần thời gian trong `hours` giờ gần nhất."""
    cutoff = now_utc() - timedelta(hours=hours)
    stmt = (
        select(SentimentScore)
        .where(
            SentimentScore.coin_id == coin_id,
            SentimentScore.calculated_at >= cutoff,
        )
        .order_by(SentimentScore.calculated_at.asc())
        .limit(limit)
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        return list(result.scalars().all())
