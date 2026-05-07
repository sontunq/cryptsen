import logging
import time
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime

from clients.http_client import shared_client
from core.time import now_vn

log = logging.getLogger(__name__)

RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"

MACRO_KEYWORDS = [
    "Fed",
    "FOMC",
    "Federal Reserve",
    "interest rate",
    "CPI",
    "inflation",
    "NFP",
    "payroll",
    "GDP",
    "unemployment",
    "Iran",
    "tariff",
    "macro",
    "dollar",
    "Treasury",
    "DXY",
    "yield",
    "recession",
]

# Cache toàn bộ feed 10 phút — 1 fetch/cycle, KHÔNG 1 fetch/coin
# (quy tắc 9). Dùng chung cho fetch_coin_news + fetch_macro_news.
_CACHE_TTL = 600
_cache: dict = {"ts": 0.0, "items": []}


async def _fetch_rss_cached() -> list[dict]:
    """Cache toàn bộ feed 10 phút. Giữ cache cũ nếu fetch lỗi."""
    now_ts = time.monotonic()
    if _cache["items"] and now_ts - _cache["ts"] < _CACHE_TTL:
        return _cache["items"]

    client = shared_client()
    try:
        resp = await client.get(RSS_URL, timeout=10)
        root = ET.fromstring(resp.text)
    except Exception as e:
        log.warning(f"CoinDesk RSS lỗi: {e}")
        return _cache["items"]  # Giữ cache cũ khi fail

    cutoff = now_vn() - timedelta(hours=24)
    items: list[dict] = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "") or ""
        url = item.findtext("link", "") or ""
        pub_str = item.findtext("pubDate", "") or ""
        description = item.findtext("description", "") or ""
        if not url:
            continue
        try:
            pub = parsedate_to_datetime(pub_str)  # tz-aware RFC 2822
            if pub.astimezone(cutoff.tzinfo) < cutoff:
                continue
        except Exception:
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "description": description,
                "published_at": pub,
            }
        )

    _cache["ts"] = now_ts
    _cache["items"] = items
    return items


async def fetch_coin_news(coin_symbol: str) -> list[dict]:
    """Lọc bài có tên coin trong title/description. Dùng chung cache feed."""
    try:
        all_items = await _fetch_rss_cached()
    except Exception as e:
        log.warning(f"fetch_coin_news lỗi: {e}")
        return []
    needle = coin_symbol.upper()
    return [
        i
        for i in all_items
        if needle in (i["title"] + i["description"]).upper()
    ]


async def fetch_macro_news() -> list[dict]:
    """Lọc bài có keyword vĩ mô. Dùng chung cache feed."""
    try:
        all_items = await _fetch_rss_cached()
    except Exception as e:
        log.warning(f"fetch_macro_news lỗi: {e}")
        return []
    return [
        i
        for i in all_items
        if any(
            kw.lower() in (i["title"] + i["description"]).lower()
            for kw in MACRO_KEYWORDS
        )
    ]
