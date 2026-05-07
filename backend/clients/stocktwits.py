"""Stocktwits public stream — không cần API key.

Endpoint: GET https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json
  ?limit=30  (max 30 per request, không cần auth với symbol phổ biến)

Sentiment tag: mỗi message có thể có sentiment.basic = "Bullish" | "Bearish".
Post không có sentiment tag → coi là neutral.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from clients.http_client import shared_client
from core.time import now_vn

log = logging.getLogger(__name__)

_CACHE_TTL = 1800  # 30 phút
_sym_cache: dict[str, tuple[float, list[dict]]] = {}
_sym_locks: dict[str, asyncio.Lock] = {}

# Stocktwits dùng $ prefix: $BTC, $ETH — map symbol crypto sang định dạng này.
# Với một số coin nhỏ Stocktwits có thể không có, sẽ trả messages=[] → bỏ qua.
_ST_SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTC.X",
    "ETH": "ETH.X",
    "SOL": "SOL.X",
    "BNB": "BNB.X",
    "XRP": "XRP.X",
    "ADA": "ADA.X",
    "DOGE": "DOGE.X",
    "AVAX": "AVAX.X",
    "DOT": "DOT.X",
    "MATIC": "MATIC.X",
    "LINK": "LINK.X",
    "LTC": "LTC.X",
    "TRX": "TRX.X",
    "SHIB": "SHIB.X",
    "TON": "TON.X",
    "NEAR": "NEAR.X",
    "UNI": "UNI.X",
    "ARB": "ARB.X",
    "OP": "OP.X",
    "ATOM": "ATOM.X",
    "APT": "APT.X",
    "FIL": "FIL.X",
    "ICP": "ICP.X",
    "HBAR": "HBAR.X",
    "ALGO": "ALGO.X",
    "VET": "VET.X",
    "XLM": "XLM.X",
    "ETC": "ETC.X",
    "BCH": "BCH.X",
    "XMR": "XMR.X",
}

_BASE_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _sentiment_label(msg: dict) -> str:
    """Lấy sentiment tag Bullish/Bearish nếu có."""
    sent = (msg.get("entities") or {}).get("sentiment") or {}
    basic = sent.get("basic", "")
    if basic == "Bullish":
        return "positive"
    if basic == "Bearish":
        return "negative"
    return "neutral"


def _sentiment_score(label: str) -> float:
    return {"positive": 7.5, "negative": 2.5, "neutral": 5.0}.get(label, 5.0)


async def _fetch_stream(st_symbol: str, max_retry: int = 2) -> list[dict]:
    """Fetch 30 messages gần nhất cho 1 symbol từ Stocktwits public API."""
    url = _BASE_URL.format(symbol=st_symbol)
    client = shared_client()
    delay = 1.0
    for attempt in range(max_retry):
        try:
            resp = await client.get(
                url,
                params={"limit": 30},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("messages") or []
            if resp.status_code == 429:
                log.warning(
                    f"Stocktwits rate-limit {st_symbol} — retry sau {delay}s"
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 404:
                log.debug(f"Stocktwits {st_symbol}: symbol không tồn tại")
                return []
            log.warning(f"Stocktwits {st_symbol} HTTP {resp.status_code}")
            return []
        except Exception as e:
            log.warning(f"Stocktwits {st_symbol} lỗi: {e!r}")
            return []
    return []


async def _get_symbol_posts(coin_symbol: str) -> list[dict]:
    """Lấy posts Stocktwits cho 1 coin (cache 30 phút)."""
    st_symbol = _ST_SYMBOL_MAP.get(coin_symbol.upper())
    if not st_symbol:
        return []

    cache_key = st_symbol
    now_ts = time.monotonic()
    cached = _sym_cache.get(cache_key)
    if cached and now_ts - cached[0] < _CACHE_TTL:
        return cached[1]

    lock = _sym_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        now_ts = time.monotonic()
        cached = _sym_cache.get(cache_key)
        if cached and now_ts - cached[0] < _CACHE_TTL:
            return cached[1]

        cutoff = now_vn() - timedelta(hours=24)
        raw_msgs = await _fetch_stream(st_symbol)
        posts: list[dict] = []
        for msg in raw_msgs:
            body = (msg.get("body") or "").strip()
            if not body or len(body) < 5:
                continue
            pub = _parse_ts(msg.get("created_at") or "")
            if pub is None:
                continue
            if pub.astimezone(cutoff.tzinfo) <= cutoff:
                continue
            msg_id = str(msg.get("id", ""))
            label = _sentiment_label(msg)
            posts.append(
                {
                    "id": msg_id,
                    "title": body[:300],
                    "body": body[:500],
                    "url": f"https://stocktwits.com/message/{msg_id}",
                    "channel": f"stocktwits/{st_symbol}",
                    "views": msg.get("likes", {}).get("total", 0) if isinstance(msg.get("likes"), dict) else 0,
                    "published_at": pub,
                    "sentiment_label": label,
                    "sentiment_score": _sentiment_score(label),
                }
            )

        _sym_cache[cache_key] = (time.monotonic(), posts)
        log.info(f"Stocktwits {st_symbol}: fetched {len(posts)} posts (24h)")
        return posts


async def fetch_stocktwits_posts(coin_symbol: str) -> list[dict]:
    """Public interface: trả list post 24h qua của coin từ Stocktwits."""
    return await _get_symbol_posts(coin_symbol)
