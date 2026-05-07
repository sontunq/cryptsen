import logging

from fastapi import APIRouter, HTTPException, Query

from core.config import settings
from core.time import now_utc
from repositories import coin_repo, sentiment_repo
from services.score_engine import build_narrative, compute_coin, get_color

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["coins"])


def _serialize(coin, snap) -> dict:
    """Gộp Coin ORM + SentimentScore snapshot gần nhất (có thể None) → dict."""
    if snap is None:
        return {
            "id": coin.id,
            "symbol": coin.symbol,
            "name": coin.name,
            "image_url": coin.image_url,
            "rank": coin.rank,
            "score_total": 0,
            "score_news": 0,
            "score_macro": 0,
            "score_social": 0,
            "social_mentions": None,
            "score_sentiment": 0,
            "label": "Không có dữ liệu",
            "color": "#6b7280",
            "summary": None,
            "calculated_at": None,
        }
    summary = snap.summary
    # Backfill narrative cho snapshot cũ (trước khi build_narrative ra đời).
    if not summary and snap.label and snap.label != "Không có dữ liệu":
        summary = build_narrative(
            coin.symbol,
            {
                "news": snap.score_news,
                "macro": snap.score_macro,
                "social": snap.score_social,
                "sentiment": snap.score_sentiment,
            },
            snap.label,
            snap.social_mentions,
        )
    return {
        "id": coin.id,
        "symbol": coin.symbol,
        "name": coin.name,
        "image_url": coin.image_url,
        "rank": coin.rank,
        "score_total": snap.score_total,
        "score_news": snap.score_news,
        "score_macro": snap.score_macro,
        "score_social": snap.score_social if snap.score_social is not None else 3.0,
        "social_mentions": snap.social_mentions,
        "score_funding": snap.score_sentiment,
        "label": snap.label,
        "color": get_color(snap.label),
        "summary": summary,
        "calculated_at": (
            snap.calculated_at.isoformat() if snap.calculated_at else None
        ),
    }


@router.get("/coins")
async def get_coins():
    coins = await coin_repo.get_sorted_by_rank()
    coins = coins[: max(100, int(settings.binance_top_coins))]

    snaps = await sentiment_repo.last_snapshots_bulk([c.id for c in coins])

    out = []
    latest_ts = None
    for c in coins:
        snap = snaps.get(c.id)
        out.append(_serialize(c, snap))
        if snap and snap.calculated_at:
            if latest_ts is None or snap.calculated_at > latest_ts:
                latest_ts = snap.calculated_at
    return {
        "coins": out,
        "last_updated": (
            latest_ts.isoformat() if latest_ts else now_utc().isoformat()
        ),
    }


@router.get("/coins/{coin_id}")
async def get_coin(coin_id: str):
    coin = await coin_repo.get_by_id(coin_id)
    if coin is None:
        raise HTTPException(status_code=404, detail="Coin not found")
    snap = await sentiment_repo.last_snapshot(coin_id)
    return _serialize(coin, snap)


@router.get("/coins/{coin_id}/history")
async def get_coin_history(
    coin_id: str,
    hours: int = Query(default=72, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Lịch sử điểm sentiment theo thời gian (mặc định 72h, tối đa 7 ngày).
    Trả list snapshot tăng dần theo thời gian — dùng để vẽ biểu đồ trend.
    """
    coin = await coin_repo.get_by_id(coin_id)
    if coin is None:
        raise HTTPException(status_code=404, detail="Coin not found")
    rows = await sentiment_repo.get_history(coin_id, hours=hours, limit=limit)
    return {
        "coin_id": coin_id,
        "symbol": coin.symbol,
        "hours": hours,
        "history": [
            {
                "calculated_at": r.calculated_at.isoformat() if r.calculated_at else None,
                "score_total": r.score_total,
                "score_news": r.score_news,
                "score_macro": r.score_macro,
                "score_social": r.score_social,
                "score_funding": r.score_sentiment,
                "label": r.label,
                "color": get_color(r.label),
            }
            for r in rows
        ],
    }


@router.post("/coins/{coin_id}/analyze")
async def analyze_coin(coin_id: str):
    """Tính fresh sentiment cho coin (news 24h + social 24h + macro + funding)
    ngay khi người dùng mở trang detail — không đợi scheduler cycle tiếp
    theo. Trả snapshot mới sau khi compute_coin ghi DB.

    compute_coin đã wrap từng source bằng _safe với SOURCE_TIMEOUT nên
    request này có trần thời gian ~SOURCE_TIMEOUT*2 (~3 phút worst-case).
    """
    coin = await coin_repo.get_by_id(coin_id)
    if coin is None:
        raise HTTPException(status_code=404, detail="Coin not found")
    try:
        await compute_coin(coin.id, coin.symbol, coin.name, coin_rank=coin.rank)
    except Exception as e:
        # compute_coin đã safe từng source — nếu vẫn bubble exception ra
        # thì log + trả snapshot hiện có (không làm trắng trang).
        log.exception(f"analyze_coin {coin.symbol} lỗi: {e}")
    snap = await sentiment_repo.last_snapshot(coin_id)
    return _serialize(coin, snap)
