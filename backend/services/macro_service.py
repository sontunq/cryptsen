"""Macro sentiment — kết hợp 2 nguồn độc lập:

  1. **Lịch kinh tế USD (FRED)** — 7 ngày gần nhất: CPI, Fed rate, DXY,
     10Y yield, Unemployment. Mỗi series so sánh observation mới với
     observation trước → điểm 0-10 (trend score).
  2. **Tin tức vĩ mô THẾ GIỚI** — CoinDesk + Investing.com (lọc bỏ tin
     coin-specific). Sentiment model → điểm cảm xúc 0-10.

Điểm macro cuối cùng là KẾT HỢP PHI TUYẾN của 2 nguồn (KHÔNG phải
trung bình đơn giản) — xem `_combine_scores`.
"""
import hashlib
import logging
from datetime import datetime, timedelta

from analyzers.sentiment import analyze_texts_async
from clients.coindesk_news import fetch_macro_news as fetch_coindesk_macro
from clients.fred import SERIES, fetch_series, fetch_upcoming_releases
from clients.telegram import fetch_telegram_macro_news
from core.time import format_vn, now_utc
from repositories import macro_repo, news_repo

log = logging.getLogger(__name__)

# Cửa sổ lịch kinh tế (ngày) theo yêu cầu sản phẩm.
FRED_WINDOW_DAYS = 7

# Cache in-memory — read-layer cho tốc độ. DB là nguồn sự thật (quy tắc 8).
_macro_cache: dict = {
    "score": 5.0,
    "events": [],
    "upcoming_events": [],
    "news": [],
    "fred_score": None,
    "news_score": None,
    "updated_at": None,
}


def _trend_score(current: float, prev: float, direction: str) -> float:
    """Map phần trăm thay đổi → score 0-10.
    - direction="down_positive": giảm → điểm cao (>5).
    - direction="up_positive":   tăng → điểm cao (>5).
    Ngưỡng ±3% thay đổi → 10/0 cực đại, <0.2% → neutral 5.
    """
    if prev == 0:
        return 5.0
    pct = (current - prev) / abs(prev) * 100
    # Clamp ±3% → 0..10
    clamped = max(-3.0, min(3.0, pct))
    # Mỗi 0.6% = 1 điểm; 0% = 5 điểm
    score = 5.0 + (clamped / 0.6)
    if direction == "down_positive":
        score = 10.0 - score
    return round(max(0.0, min(10.0, score)), 2)


def _trend_label(score: float) -> str:
    if score >= 6:
        return "positive"
    if score <= 4:
        return "negative"
    return "neutral"


_IMPACT_MAP = {
    # CPI, Fed rate, 10Y yield, DXY → tác động mạnh tới crypto
    "CPIAUCSL": "High",
    "DFF": "High",
    "DGS10": "High",
    "DTWEXBGS": "High",
    # Unemployment → trung bình (ảnh hưởng gián tiếp qua kỳ vọng Fed)
    "UNRATE": "Medium",
}


def _impact_of(series_id: str) -> str:
    return _IMPACT_MAP.get(series_id, "Medium")


def _consequence(series_id: str, change_pct: float, label: str) -> str:
    """Chuỗi giải thích hệ quả cho người đọc.
    Dạng: "USD tăng → BTC giảm (Tin xấu)" hoặc tương tự, tuỳ series.
    """
    if abs(change_pct) < 0.01:
        return "Không đổi → Ảnh hưởng trung tính"
    up = change_pct > 0
    arrow_usd_up = "USD mạnh lên → crypto chịu áp lực giảm"
    arrow_usd_dn = "USD yếu đi → dòng tiền chảy vào crypto"
    mapping = {
        "CPIAUCSL": (
            "Lạm phát tăng → Fed có thể thắt chặt → " + arrow_usd_up
            if up
            else "Lạm phát hạ nhiệt → Fed có dư địa nới lỏng → " + arrow_usd_dn
        ),
        "DFF": (
            "Lãi suất Fed tăng → " + arrow_usd_up
            if up
            else "Lãi suất Fed giảm → " + arrow_usd_dn
        ),
        "DGS10": (
            "Lợi suất 10Y tăng → dòng tiền rời tài sản rủi ro → BTC giảm"
            if up
            else "Lợi suất 10Y giảm → khẩu vị rủi ro tăng → BTC tăng"
        ),
        "DTWEXBGS": (
            "DXY tăng → " + arrow_usd_up
            if up
            else "DXY giảm → " + arrow_usd_dn
        ),
        "UNRATE": (
            "Thất nghiệp tăng → Fed có khả năng cắt giảm lãi suất → BTC hưởng lợi"
            if up
            else "Thất nghiệp giảm → kinh tế mạnh → Fed diều hâu → BTC chịu áp lực"
        ),
    }
    base = mapping.get(series_id, "")
    verdict = {
        "positive": " (Tin tốt cho crypto)",
        "negative": " (Tin xấu cho crypto)",
        "neutral": " (Ảnh hưởng trung tính)",
    }.get(label, "")
    return base + verdict


def _make_id(series_id: str, date_str: str) -> str:
    return hashlib.sha1(f"{series_id}|{date_str}".encode()).hexdigest()[:16]


def _news_score_label(score: float) -> str:
    if score >= 6:
        return "positive"
    if score <= 4:
        return "negative"
    return "neutral"


def _combine_scores(
    fred_score: float | None,
    news_score: float | None,
) -> float:
    """Kết hợp điểm FRED + tin tức vĩ mô thành 1 điểm macro 0-10.

    *Không* phải trung bình đơn giản. Logic:
      - Base = trung bình có trọng số: FRED 60% (tín hiệu cấu trúc
        từ dữ liệu kinh tế thật), tin tức 40% (tín hiệu phản ứng
        ngắn hạn). Nếu 1 nguồn vắng mặt → dùng 100% nguồn còn lại.
      - **Agreement boost**: nếu cả 2 nguồn cùng lệch cùng hướng so
        với trung tính (5) → khuếch đại ±15% (tín hiệu đồng thuận).
      - **Disagreement dampen**: nếu 2 nguồn đối lập → giảm 15% về 5
        (tín hiệu mâu thuẫn).
      - Nếu cả 2 None → 5.0 (trung tính).
    """
    if fred_score is None and news_score is None:
        return 5.0
    if fred_score is None:
        return round(max(0.0, min(10.0, news_score)), 2)
    if news_score is None:
        return round(max(0.0, min(10.0, fred_score)), 2)

    base = 0.6 * fred_score + 0.4 * news_score
    agree = (fred_score - 5) * (news_score - 5)
    if agree > 0:
        base = 5 + (base - 5) * 1.15
    elif agree < 0:
        base = 5 + (base - 5) * 0.85
    return round(max(0.0, min(10.0, base)), 2)


async def _score_macro_news() -> tuple[float | None, list[dict]]:
    """Fetch tin vĩ mô từ 3 nguồn → sentiment model → điểm trung bình 0-10.

    Nguồn:
      • CoinDesk API/RSS  → source='macro-coindesk'
      • Investing.com RSS → source='macro-investing'
      • Telegram channels → source='macro-telegram-<channel>'

    Trả `(score, items)`. `items` đã có `sentiment_label/score` + source.
    Persist vào news_items để /api/macro-events phục vụ frontend.
    """
    coindesk  = await fetch_coindesk_macro()
    try:
        telegram_macro = await fetch_telegram_macro_news()
    except Exception as e:
        log.warning("telegram macro fetch error: %s", e)
        telegram_macro = []

    # Telegram posts mang metadata channel — đặt source riêng theo channel
    # để FE có thể filter theo nguồn cụ thể (e.g. 'macro-telegram-coindesk').
    telegram_bundles: list[tuple[str, list[dict]]] = []
    _tg_by_channel: dict[str, list[dict]] = {}
    for post in telegram_macro:
        ch_name = post.get("channel", "unknown")
        _tg_by_channel.setdefault(ch_name, []).append(post)
    for ch_name, posts in _tg_by_channel.items():
        telegram_bundles.append((f"macro-telegram-{ch_name}", posts))

    bundles: list[tuple[str, list[dict]]] = [
        ("macro-coindesk",  coindesk),
        *telegram_bundles,
    ]

    total_articles: list[dict] = []
    total_source:   list[str]  = []

    for src_name, items in bundles:
        if not items:
            continue
        for it in items:
            total_articles.append(it)
            total_source.append(src_name)

    if not total_articles:
        return None, []

    texts = [
        (a.get("text_for_analysis") or a.get("title") or "")
        for a in total_articles
    ]
    results = await analyze_texts_async(texts)
    if not results:
        return None, []

    enriched: list[dict] = []
    for art, res, src in zip(total_articles, results, total_source):
        enriched.append({
            "title":           art.get("title", ""),
            "url":             art.get("url", ""),
            "description":     art.get("description", "") or art.get("body", ""),
            "published_at":    art.get("published_at"),
            "source":          src,
            # Giữ channel_label nếu có (dùng cho hiển thị FE)
            "channel_label":   art.get("channel_label", ""),
            "sentiment_label": res.get("label", "neutral"),
            "sentiment_score": float(res.get("score", 5.0)),
        })

    # Persist — gom theo source_name để bulk_insert hiệu quả
    try:
        by_src: dict[str, tuple[list, list]] = {}
        for art, res, src in zip(total_articles, results, total_source):
            by_src.setdefault(src, ([], []))
            by_src[src][0].append(art)
            by_src[src][1].append(res)
        for src, (arts, rss) in by_src.items():
            urls     = [a["url"] for a in arts if a.get("url")]
            existing = await news_repo.exists_many(urls) if urls else set()
            new_arts = [a for a in arts if a.get("url") and a["url"] not in existing]
            new_rss  = [r for a, r in zip(arts, rss) if a.get("url") and a["url"] not in existing]
            if new_arts:
                await news_repo.bulk_insert(new_arts, new_rss, None, src)
    except Exception as e:
        log.warning("persist macro news error: %s", e)

    avg = sum(r["sentiment_score"] for r in enriched) / len(enriched)
    return round(avg, 2), enriched


async def load_cache_from_db() -> None:
    """Restore cache sau restart — dùng events đã lưu 7 ngày qua."""
    global _macro_cache
    try:
        events = await macro_repo.get_recent_events(days=FRED_WINDOW_DAYS)
        if events:
            # Tách upcoming (chưa có actual) khỏi historical để tính score đúng
            historical = [e for e in events if e.get("label") != "upcoming"]
            upcoming   = [e for e in events if e.get("label") == "upcoming"]
            scored = historical or events  # fallback nếu DB chỉ có upcoming
            fred = sum(e["score"] for e in scored) / len(scored)
            _macro_cache = {
                "score": round(fred, 2),
                "events": historical,
                "upcoming_events": upcoming,
                "news": [],
                "fred_score": round(fred, 2),
                "news_score": None,
                "updated_at": now_utc().isoformat(),
            }
            log.info(
                f"Macro cache restored từ DB: {len(events)} events, "
                f"fred_score={fred:.2f} (news sẽ refresh ở cycle sau)"
            )
    except Exception as e:
        log.warning(f"load_cache_from_db lỗi: {e}")


async def update_macro_cache() -> None:
    """Chạy mỗi `macro_refresh_hours`:
      1. Pull FRED (USD, filter 7 ngày gần nhất) → trend score.
      2. Pull macro news (CoinDesk + Investing) → FinBERT → news score.
      3. Kết hợp 2 nguồn phi tuyến → điểm macro cuối cùng.

    Lỗi 1 nguồn/1 series KHÔNG làm hỏng toàn bộ (quy tắc 10).
    """
    global _macro_cache
    events_scored: list[dict] = []
    cutoff_date = (now_utc() - timedelta(days=FRED_WINDOW_DAYS)).date()

    for series_id, meta in SERIES.items():
        try:
            obs = await fetch_series(series_id, limit=2)
            if len(obs) < 2:
                log.warning(f"FRED {series_id}: không đủ data (n={len(obs)})")
                continue
            current, prev = obs[0], obs[1]
            # Filter: chỉ giữ observation mới nhất trong cửa sổ 7 ngày.
            try:
                cur_date = datetime.fromisoformat(current["date"]).date()
                if cur_date < cutoff_date:
                    continue
            except Exception:
                continue
            score = _trend_score(current["value"], prev["value"], meta["direction"])
            label = _trend_label(score)
            change_pct = (
                (current["value"] - prev["value"]) / abs(prev["value"]) * 100
                if prev["value"]
                else 0.0
            )
            events_scored.append(
                {
                    "id": _make_id(series_id, current["date"]),
                    "event": meta["name"],
                    "series_id": series_id,
                    "date": current["date"],
                    "time": "",
                    "currency": "USD",
                    "impact": _impact_of(series_id),
                    "actual": f"{current['value']:.3f} {meta['unit']}",
                    "forecast": "",
                    "previous": f"{prev['value']:.3f} {meta['unit']}",
                    "change_pct": round(change_pct, 3),
                    "direction": meta["direction"],
                    "consequence": _consequence(series_id, change_pct, label),
                    "score": score,
                    "label": label,
                }
            )
        except Exception as e:
            log.warning(f"FRED series {series_id} lỗi: {e}")

    fred_score = (
        round(sum(e["score"] for e in events_scored) / len(events_scored), 2)
        if events_scored
        else None
    )

    # Macro news (CoinDesk + Investing) — lỗi thì news_score=None.
    try:
        news_score, news_items = await _score_macro_news()
    except Exception as e:
        log.warning(f"score_macro_news lỗi: {e}")
        news_score, news_items = None, []

    if fred_score is None and news_score is None:
        log.warning("Macro: cả FRED và news đều trống — giữ cache cũ")
        return

    combined = _combine_scores(fred_score, news_score)

    # Lịch kinh tế sắp tới (không ảnh hưởng đến điểm — chỉ hiển thị)
    try:
        upcoming_raw = await fetch_upcoming_releases(days_ahead=30)
        upcoming_events = [
            {
                "id":       f"upcoming-{r['release_id']}-{r['date']}",
                "event":    r["name"],
                "date":     r["date"],
                "time":     "",
                "currency": "USD",
                "impact":   r["impact"],
                "actual":   "",
                "forecast": "",
                "previous": "",
                "score":    5.0,
                "label":    "upcoming",
                "is_upcoming": True,
            }
            for r in upcoming_raw
        ]
    except Exception as e:
        log.warning(f"fetch_upcoming_releases lỗi: {e}")
        upcoming_events = []

    _macro_cache = {
        "score": combined,
        "events": events_scored,
        "upcoming_events": upcoming_events,
        "news": news_items,
        "fred_score": fred_score,
        "news_score": news_score,
        "updated_at": now_utc().isoformat(),
    }

    try:
        if events_scored:
            await macro_repo.upsert_events(events_scored)
        # upcoming_events KHÔNG lưu DB — chỉ dùng hiển thị/RAG, không tính điểm
    except Exception as e:
        log.warning(f"upsert_events lỗi: {e}")

    fred_disp = f"{fred_score:.2f}" if fred_score is not None else "—"
    news_disp = f"{news_score:.2f}" if news_score is not None else "—"
    log.info(
        f"[{format_vn(now_utc())}] Macro: combined={combined:.2f} "
        f"(fred={fred_disp} n={len(events_scored)}, "
        f"news={news_disp} n={len(news_items)})"
    )


def get_macro_score() -> float:
    return _macro_cache.get("score", 5.0)


_NAME_TO_SERIES = {meta["name"]: sid for sid, meta in SERIES.items()}


def _parse_numeric(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(s.split()[0])
    except (ValueError, IndexError):
        return None


def _enrich_event(ev: dict) -> dict:
    """Bổ sung series_id / change_pct / consequence cho event load từ DB."""
    if ev.get("consequence"):
        return ev
    sid = ev.get("series_id") or _NAME_TO_SERIES.get(ev.get("event", ""))
    if not sid:
        return ev
    cur = _parse_numeric(ev.get("actual", ""))
    prev = _parse_numeric(ev.get("previous", ""))
    change = (
        (cur - prev) / abs(prev) * 100 if (cur is not None and prev) else 0.0
    )
    return {
        **ev,
        "series_id": sid,
        "direction": SERIES[sid]["direction"],
        "impact": ev.get("impact") or _impact_of(sid),
        "change_pct": round(change, 3),
        "consequence": _consequence(sid, change, ev.get("label", "neutral")),
    }


async def get_macro_events() -> list[dict]:
    """Trả historical events đã có dữ liệu thực tế. Fallback DB nếu cache rỗng."""
    if _macro_cache.get("events"):
        return [_enrich_event(e) for e in _macro_cache["events"]]
    try:
        rows = await macro_repo.get_recent_events(days=FRED_WINDOW_DAYS)
        return [_enrich_event(e) for e in rows]
    except Exception as e:
        log.warning(f"get_macro_events fallback DB lỗi: {e}")
        return []


def get_upcoming_events() -> list[dict]:
    """Trả lịch sự kiện kinh tế sắp tới (chưa có actual). Chỉ từ memory cache."""
    return list(_macro_cache.get("upcoming_events") or [])


def _serialize_news(item: dict) -> dict:
    pub = item.get("published_at")
    if hasattr(pub, "isoformat"):
        pub = pub.isoformat()
    return {
        "title":         item.get("title", ""),
        "url":           item.get("url", ""),
        "description":   item.get("description", ""),
        "published_at":  pub,
        "source":        item.get("source", "macro"),
        # channel_label: tên hiển thị thân thiện của kênh Telegram (nếu có)
        "channel_label": item.get("channel_label", ""),
        "sentiment_label": item.get("sentiment_label", "neutral"),
        "sentiment_score": item.get("sentiment_score", 5.0),
    }


async def get_macro_news() -> list[dict]:
    """Trả tin tức vĩ mô đã chấm điểm. Fallback DB theo source prefix
    'macro-*' nếu memory cache rỗng."""
    cached = _macro_cache.get("news") or []
    if cached:
        return [_serialize_news(n) for n in cached]
    # Fallback từ DB — query toàn bộ source có prefix 'macro-'
    try:
        from sqlalchemy import select
        from core.db import AsyncSessionLocal
        from models.database import NewsItem

        async with AsyncSessionLocal() as session:
            stmt = (
                select(NewsItem)
                .where(NewsItem.source.like("macro-%"))
                .order_by(NewsItem.published_at.desc())
                .limit(60)
            )
            result = await session.execute(stmt)
            rows   = result.scalars().all()

        out: list[dict] = [
            {
                "title":           r.title,
                "url":             r.url,
                "description":     "",
                "published_at":    r.published_at.isoformat() if r.published_at else None,
                "source":          r.source,
                "channel_label":   "",   # không lưu trong DB, để trống
                "sentiment_label": r.sentiment_label,
                "sentiment_score": r.sentiment_score,
            }
            for r in rows
        ]
        return out
    except Exception as e:
        log.warning("get_macro_news fallback DB error: %s", e)
        return []
