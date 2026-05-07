from fastapi import APIRouter, Query

from repositories import coin_repo, news_repo

router = APIRouter(prefix="/api", tags=["news"])


def _serialize(n) -> dict:
    return {
        "id": n.id,
        "coin_id": n.coin_id,
        "title": n.title,
        "url": n.url,
        "source": n.source,
        "sentiment_label": n.sentiment_label,
        "sentiment_score": n.sentiment_score,
        "reason": n.reason,
        "upvotes": n.upvotes,
        "num_comments": n.num_comments,
        "published_at": (
            n.published_at.isoformat() if n.published_at else None
        ),
        "crawled_at": n.crawled_at.isoformat() if n.crawled_at else None,
    }


@router.get("/news")
async def get_news(
    coin_id: str | None = Query(default=None),
    source: str | None = Query(
        default=None,
        description=(
            "Lọc theo nguồn. Các giá trị hợp lệ: coindesk, reddit, telegram, "
            "macro-coindesk, macro-investing, macro-telegram-<channel>, all."
        ),
    ),
    sentiment: str | None = Query(
        default=None, pattern="^(positive|neutral|negative|all)$"
    ),
    hours: int | None = Query(default=None, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Feed tin tức — dùng composite index `ix_news_filter` (Phase 1).

    `coin_id` param chấp nhận cả CoinGecko id (vd "bitcoin") và symbol
    ("BTC"). Nếu là id dài → resolve sang symbol qua coin_repo.

    `source` có thể là prefix 'macro-telegram-<channel>' cho từng kênh
    Telegram riêng, hoặc 'all' để lấy tất cả.
    """
    if coin_id and coin_id.lower() != "all":
        # Heuristic: symbol ≤ 6 ký tự, id CoinGecko thường dài hơn.
        if len(coin_id) > 6 or "-" in coin_id or coin_id.islower():
            coin = await coin_repo.get_by_id(coin_id.lower())
            if coin is not None:
                coin_id = coin.symbol
    rows = await news_repo.query_news(
        coin_id=coin_id,
        source=source,
        sentiment=sentiment,
        hours=hours,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_serialize(n) for n in rows],
        "limit": limit,
        "offset": offset,
        "count": len(rows),
    }


@router.get("/telegram-channels")
async def get_telegram_channels():
    """Trả danh sách các Telegram channel đang được cào dữ liệu.

    Dùng cho frontend để hiển thị badge nguồn tin hoặc filter UI.
    """
    from clients.telegram import get_channel_registry
    channels = get_channel_registry()
    return {
        "channels": channels,
        "count": len(channels),
    }
