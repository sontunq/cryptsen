import hashlib
import logging
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.db import AsyncSessionLocal
from core.time import now_utc
from models.database import NewsItem

log = logging.getLogger(__name__)


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _map_label(label: str) -> str:
    """Map Gemini / FinBERT label về 3 giá trị chuẩn."""
    l = (label or "").lower()
    if l in ("positive", "pos", "tích cực", "tich cuc"):
        return "positive"
    if l in ("negative", "neg", "tiêu cực", "tieu cuc"):
        return "negative"
    return "neutral"


async def exists_many(urls: list[str]) -> set[str]:
    """Batch check URL đã có trong DB — quy tắc 9 (KHÔNG loop N+1).
    Trả về SET các URL đã tồn tại."""
    if not urls:
        return set()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(NewsItem.url).where(NewsItem.url.in_(urls))
        )
        return {row[0] for row in result.all()}


async def bulk_insert(
    items: list[dict],
    analyses: list[dict],
    coin_symbol: str | None,
    source: str,
) -> int:
    """Insert tin tức batch với `ON CONFLICT(url) DO NOTHING` (quy tắc 9).

    `items` và `analyses` cùng độ dài — phần tử thứ i là cặp bài + kết quả.
    Item của nguồn Reddit phải có `upvotes` + `num_comments` (quy tắc 21).
    `coin_symbol` = None đối với tin macro.
    """
    if not items or not analyses or len(items) != len(analyses):
        return 0

    coin_id = None
    # Tin tức coin (CoinDesk / Reddit) gắn với symbol — Phase 4 query theo symbol.
    # NewsItem.coin_id lưu symbol UPPER để tiện filter (FK chưa có ràng buộc
    # cứng vào bảng coins vì 1 tin có thể thuộc nhiều coin).
    if coin_symbol:
        coin_id = coin_symbol.upper()

    now = now_utc()
    rows: list[dict] = []
    seen_urls: set[str] = set()
    for item, an in zip(items, analyses):
        url = item.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        # Reddit post có thể nhắc nhiều coin. Nếu giữ URL gốc thì ràng buộc
        # unique(url) khiến bài chỉ thuộc coin đầu tiên được insert.
        # Gắn suffix theo coin để mỗi coin có bản ghi riêng cho cùng 1 post.
        stored_url = url
        if source == "reddit" and coin_id:
            stored_url = f"{url}#coin={coin_id}"

        rows.append(
            {
                "id": _url_hash(stored_url),
                "coin_id": coin_id,
                "title": item.get("title", "")[:1000],
                "url": stored_url,
                "source": source,
                "sentiment_label": _map_label(an.get("label", "neutral")),
                "sentiment_score": float(an.get("score", 5.0)),
                "reason": an.get("reason"),
                "upvotes": item.get("upvotes"),
                "num_comments": item.get("num_comments"),
                "published_at": item.get("published_at"),
                "crawled_at": now,
            }
        )

    if not rows:
        return 0

    # ON CONFLICT(url) DO NOTHING — quy tắc 9: tránh crash khi cycle lặp.
    stmt = sqlite_insert(NewsItem).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=[NewsItem.url])
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()
    return len(rows)


async def avg_score(
    coin_symbol: str | None, source: str, hours: int = 24
) -> float | None:
    """Điểm trung bình (thang 0–10) của tin trong N giờ qua — fallback
    khi không có bài mới trong cycle hiện tại."""
    cutoff = now_utc() - timedelta(hours=hours)
    stmt = select(func.avg(NewsItem.sentiment_score)).where(
        NewsItem.source == source,
        NewsItem.crawled_at >= cutoff,
    )
    if coin_symbol:
        stmt = stmt.where(NewsItem.coin_id == coin_symbol.upper())

    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        val = result.scalar()
        return float(val) if val is not None else None


async def query_news(
    coin_id: str | None = None,
    source: str | None = None,
    sentiment: str | None = None,
    hours: int | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[NewsItem]:
    """Feed `/api/news` — filter theo composite index `ix_news_filter`."""
    stmt = select(NewsItem)
    if coin_id and coin_id.lower() != "all":
        stmt = stmt.where(NewsItem.coin_id == coin_id.upper())
    if source and source.lower() != "all":
        stmt = stmt.where(NewsItem.source == source.lower())
    if sentiment and sentiment.lower() != "all":
        stmt = stmt.where(NewsItem.sentiment_label == sentiment.lower())
    if hours is not None and hours > 0:
        cutoff = now_utc() - timedelta(hours=hours)
        stmt = stmt.where(NewsItem.published_at >= cutoff)
    stmt = (
        stmt.order_by(NewsItem.published_at.desc())
        .limit(limit)
        .offset(offset)
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def delete_stale_by_coin_source(
    coin_symbol: str,
    source: str,
    keep_hours: int = 48,
) -> int:
    """Xóa bản ghi TIN CŨ HƠN keep_hours giờ theo coin + source.

    Dùng mỗi cycle để dọn sạch bài CoinDesk bị insert nhầm từ
    logic filter cũ (false-positive), tránh chúng tồn tại mãi trong DB.
    Chỉ giữ lại bài trong cửa sổ keep_hours gần nhất.
    """
    cutoff = now_utc() - timedelta(hours=keep_hours)
    stmt = delete(NewsItem).where(
        NewsItem.coin_id == coin_symbol.upper(),
        NewsItem.source == source.lower(),
        NewsItem.crawled_at < cutoff,
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        await session.commit()
        return int(result.rowcount or 0)


async def delete_recent_by_coin_source(
    coin_symbol: str,
    source: str,
    hours: int = 24,
) -> int:
    """Xoá bản ghi tin gần đây theo coin + source.

    Dùng để đồng bộ feed với kết quả analyze mới nhất (tránh giữ dữ liệu cũ
    từ logic match trước đó).
    """
    cutoff = now_utc() - timedelta(hours=hours)
    stmt = delete(NewsItem).where(
        NewsItem.coin_id == coin_symbol.upper(),
        NewsItem.source == source.lower(),
        NewsItem.published_at >= cutoff,
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        await session.commit()
        return int(result.rowcount or 0)
