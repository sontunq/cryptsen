from fastapi import APIRouter

from services import macro_service

router = APIRouter(prefix="/api", tags=["macro"])


@router.post("/macro-refresh")
async def refresh_macro():
    """Trigger cập nhật macro cache thủ công (dùng để debug/test)."""
    await macro_service.update_macro_cache()
    events = await macro_service.get_macro_events()
    return {"ok": True, "events_count": len(events)}


@router.get("/macro-events")
async def get_macro_events():
    """Cache từ `services.macro_service`. Trả đồng thời lịch kinh tế
    (FRED, 7 ngày USD) + tin tức vĩ mô thế giới (CoinDesk + Investing + Telegram).
    Fallback DB nếu memory cache rỗng (quy tắc 8)."""
    from clients.telegram import CHANNEL_REGISTRY

    events = await macro_service.get_macro_events()
    news   = await macro_service.get_macro_news()
    from services.macro_service import _macro_cache

    # Sử dụng tên channel thực tế từ registry thay vì hard-code
    tg_sources = [
        f"macro-telegram-{ch['username']}"
        for ch in CHANNEL_REGISTRY
        if ch["focus"] in ("macro", "both")
    ]
    all_sources = ["macro-coindesk", "macro-investing"] + tg_sources

    upcoming = macro_service.get_upcoming_events()
    return {
        "score":          macro_service.get_macro_score(),
        "fred_score":     _macro_cache.get("fred_score"),
        "news_score":     _macro_cache.get("news_score"),
        "events":         events,
        "upcoming_events": upcoming,
        "news":           news,
        "count":          len(events),
        "news_count":     len(news),
        "sources":        all_sources,
    }
