import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import timedelta
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from clients.http_client import shared_client
from core.config import settings

log = logging.getLogger(__name__)


def _word_match(needle: str, haystack: str) -> bool:
    """Kiểm tra needle xuất hiện như 1 từ độc lập trong haystack.
    Ngăn false-positive như 'ASTER' khớp 'Mastercard' hay 'Faster'.
    Dùng \\b (word boundary) của regex.
    """
    if not needle or not haystack:
        return False
    return bool(re.search(r"\b" + re.escape(needle) + r"\b", haystack))

# CoinDesk Data API — news feed (JSON).
# Docs: https://developers.coindesk.com/documentation/data-api/news_v1_article_list
API_URL = "https://data-api.coindesk.com/news/v1/article/list"
RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"

# Giữ nguyên keyword macro như bản RSS để filter tin vĩ mô.
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
_LOOKBACK_HOURS = 24 * 7
_API_PAGE_LIMIT = 100
_MAX_API_PAGES = 20

# Giới hạn BODY đưa vào FinBERT — title + excerpt ~1800 ký tự ≈ 400 tokens,
# dưới max_length 512 của FinBERT (quy tắc 6).
_BODY_EXCERPT_CHARS = 1500

# Tên đầy đủ của coin thường xuất hiện trong title/description tin tức thay
# vì ticker (vd "Bitcoin" thay vì "BTC"). Nếu ticker không match categories/
# keywords/haystack thì fallback sang alias để không bỏ sót bài.
_NEWS_ALIASES: dict[str, list[str]] = {
    "BTC": ["BITCOIN"],
    "ETH": ["ETHEREUM", "ETHER"],
    "SOL": ["SOLANA"],
    "BNB": ["BINANCE COIN"],
    "XRP": ["RIPPLE"],
    "ADA": ["CARDANO"],
    "DOGE": ["DOGECOIN"],
    "AVAX": ["AVALANCHE"],
    "DOT": ["POLKADOT"],
    "MATIC": ["POLYGON"],
    "LINK": ["CHAINLINK"],
    "LTC": ["LITECOIN"],
    "TRX": ["TRON"],
    "SHIB": ["SHIBA", "SHIBA INU"],
    "TON": ["TONCOIN"],
    "XMR": ["MONERO"],
    "XLM": ["STELLAR"],
    "BCH": ["BITCOIN CASH"],
    "ZEC": ["ZCASH"],
    "ATOM": ["COSMOS"],
    "NEAR": ["NEAR PROTOCOL"],
    "UNI": ["UNISWAP"],
    "APT": ["APTOS"],
    "ARB": ["ARBITRUM"],
    "OP": ["OPTIMISM"],
    "FIL": ["FILECOIN"],
    "ETC": ["ETHEREUM CLASSIC"],
    "ICP": ["INTERNET COMPUTER"],
    "HBAR": ["HEDERA"],
    "ALGO": ["ALGORAND"],
    "VET": ["VECHAIN"],
    "EGLD": ["MULTIVERSX", "ELROND"],
    "XTZ": ["TEZOS"],
    "AAVE": ["AAVE"],
    "CRO": ["CRONOS"],
    "LEO": ["UNUS SED LEO"],
}


def _parse_ts(value) -> datetime | None:
    """CoinDesk trả PUBLISHED_ON là unix timestamp (seconds, UTC)."""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


async def _fetch_api_cached() -> list[dict]:
    """Cache feed 10 phút, gom CoinDesk API + RSS trong 7 ngày.

    API list endpoint thường thiên về tin rất mới; RSS được dùng để tăng
    độ phủ các bài cũ hơn trong cửa sổ 7 ngày.
    """
    now_ts = time.monotonic()
    if _cache["items"] and now_ts - _cache["ts"] < _CACHE_TTL:
        return _cache["items"]

    headers = {"Accept": "application/json"}
    # API key là optional (CoinDesk cho phép anonymous với rate thấp).
    # Có key → header `authorization: Apikey ...` để nâng quota.
    if settings.coindesk_api_key:
        headers["authorization"] = f"Apikey {settings.coindesk_api_key}"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_HOURS)
    cutoff_ts = int(cutoff.timestamp())
    client = shared_client()

    items: list[dict] = []
    seen_urls: set[str] = set()
    to_ts: int | None = None
    page_count = 0
    while page_count < _MAX_API_PAGES:
        params = {"lang": "EN", "limit": _API_PAGE_LIMIT}
        if to_ts is not None:
            params["to_ts"] = to_ts

        try:
            resp = await client.get(
                API_URL, params=params, headers=headers, timeout=10
            )
            resp.raise_for_status()
            payload = resp.json() or {}
        except Exception as e:
            log.warning(f"CoinDesk News API lỗi: {e}")
            break

        articles = payload.get("Data") or []
        if not articles:
            break

        page_count += 1
        batch_oldest_ts: int | None = None
        for a in articles:
            pub = _parse_ts(a.get("PUBLISHED_ON"))
            if pub is None:
                continue
            pub_ts = int(pub.timestamp())
            if batch_oldest_ts is None or pub_ts < batch_oldest_ts:
                batch_oldest_ts = pub_ts

            if pub_ts < cutoff_ts:
                continue

            url = a.get("URL") or ""
            title = (a.get("TITLE") or "").strip()
            if not url or not title or url in seen_urls:
                continue

            body = (a.get("BODY") or "").strip()
            # Categories dạng [{"CATEGORY": "BTC"}, {"CATEGORY": "MARKET"}, ...]
            cats_raw = a.get("CATEGORY_DATA") or []
            categories = [
                str(c.get("CATEGORY", "")).upper()
                for c in cats_raw
                if c.get("CATEGORY")
            ]
            keywords = (a.get("KEYWORDS") or "").upper()

            seen_urls.add(url)
            items.append(
                {
                    "title": title,
                    "url": url,
                    "description": body[:500],  # dùng hiển thị — ngắn gọn
                    "published_at": pub,
                    "categories": categories,
                    "keywords": keywords,
                    # text_for_analysis: title + body excerpt → FinBERT nhiều signal
                    # hơn so với chỉ title (lợi ích của việc dùng API thay RSS).
                    "text_for_analysis": (
                        f"{title}. {body[:_BODY_EXCERPT_CHARS]}"
                        if body
                        else title
                    ),
                }
            )

        if batch_oldest_ts is None or batch_oldest_ts <= cutoff_ts:
            break
        next_to_ts = batch_oldest_ts - 1
        if to_ts is not None and next_to_ts >= to_ts:
            break
        to_ts = next_to_ts

    # Bổ sung RSS để phủ thêm bài cũ hơn (vẫn trong 7 ngày).
    try:
        rss_items = await _fetch_rss_recent(cutoff)
    except Exception as e:
        log.warning(f"CoinDesk RSS merge lỗi: {e}")
        rss_items = []

    seen_urls = {i["url"] for i in items}
    for r in rss_items:
        if r["url"] in seen_urls:
            continue
        seen_urls.add(r["url"])
        items.append(r)

    items.sort(
        key=lambda x: x.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    _cache["ts"] = now_ts
    _cache["items"] = items
    log.info(f"CoinDesk News 7d: fetched {len(items)} bài")
    return items


async def _fetch_rss_recent(cutoff: datetime) -> list[dict]:
    client = shared_client()
    resp = await client.get(RSS_URL, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    out: list[dict] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title", "") or "").strip()
        url = (item.findtext("link", "") or "").strip()
        desc = (item.findtext("description", "") or "").strip()
        pub_str = (item.findtext("pubDate", "") or "").strip()
        if not title or not url or not pub_str:
            continue
        try:
            pub = parsedate_to_datetime(pub_str)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            pub = pub.astimezone(timezone.utc)
        except Exception:
            continue
        if pub < cutoff:
            continue

        out.append(
            {
                "title": title,
                "url": url,
                "description": desc[:500],
                "published_at": pub,
                "categories": [],
                # RSS không có curated keywords — chỉ dùng title để tránh
                # false-positive khi description nhắc coin khác như context.
                "keywords": title.upper(),
                "text_for_analysis": (
                    f"{title}. {desc[:_BODY_EXCERPT_CHARS]}"
                    if desc
                    else title
                ),
            }
        )
    return out


async def fetch_coin_news(coin_symbol: str, coin_name: str | None = None) -> list[dict]:
    """Lọc bài liên quan tới coin. Ưu tiên match CATEGORY/KEYWORDS
    (chính xác) rồi fallback title+description (giống RSS cũ)."""
    try:
        all_items = await _fetch_api_cached()
    except Exception as e:
        log.warning(f"fetch_coin_news lỗi: {e}")
        return []
    needle = coin_symbol.upper()
    name_needle = " ".join(str(coin_name or "").upper().split())
    name_tokens = [
        t
        for t in name_needle.split()
        if len(t) >= 3 and t not in {"COIN", "TOKEN", "PROTOCOL", "NETWORK"}
    ]
    aliases = _NEWS_ALIASES.get(needle, [])
    result: list[dict] = []
    for i in all_items:
        cats = i["categories"]
        kws = i["keywords"]
        # title_upper dùng cho match chính xác (không lẫn coin khác
        # chỉ vì chúng được nhắc như context trong phần body/description).
        title_upper = i["title"].upper()

        # 1. Category (chính xác nhất — CoinDesk gán thủ công)
        if needle in cats:
            result.append(i)
            continue
        for a in aliases:
            if a in cats:
                result.append(i)
                break
        else:
            # 2. Keyword curated (CoinDesk API): dùng word boundary để tránh
            #    false-positive như 'ASTER' khớp 'Mastercard'/'Faster'.
            if _word_match(needle, kws) or _word_match(needle, title_upper):
                result.append(i)
                continue

            # 3. Alias trong keywords hoặc title (cũng cần word boundary)
            if aliases and any(
                _word_match(a, kws) or _word_match(a, title_upper) for a in aliases
            ):
                result.append(i)
                continue

            # 4. Tên coin (từ coin_name) trong title — word boundary
            if name_needle and (
                _word_match(name_needle, title_upper)
                or (
                    len(name_tokens) >= 2
                    and all(_word_match(t, title_upper) for t in name_tokens[:2])
                )
            ):
                result.append(i)
    return result


# Các CATEGORY của CoinDesk chỉ rõ 1 coin/blockchain cụ thể → nếu bài
# có bất kỳ category nào trong set này thì coi là tin "coin-specific"
# và KHÔNG tính vào macro (tránh trùng với trục "Tin tức" của coin).
_COIN_SPECIFIC_CATEGORIES = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "DOT", "TRX",
    "MATIC", "LINK", "LTC", "BCH", "ALTCOIN", "MEMECOIN", "TOKEN",
    "NFT", "DEFI", "LAYER2",
}


async def fetch_macro_news() -> list[dict]:
    """Tin vĩ mô KINH TẾ THẾ GIỚI (không gắn với 1 coin cụ thể).

    Filter 2 tầng:
      1. Có keyword macro trong title/description.
      2. KHÔNG có CATEGORY gắn với 1 coin/chain cụ thể.
    """
    try:
        all_items = await _fetch_api_cached()
    except Exception as e:
        log.warning(f"fetch_macro_news lỗi: {e}")
        return []
    out: list[dict] = []
    for i in all_items:
        haystack = (i["title"] + " " + i["description"]).lower()
        if not any(kw.lower() in haystack for kw in MACRO_KEYWORDS):
            continue
        cats = set(i.get("categories") or [])
        if cats & _COIN_SPECIFIC_CATEGORIES:
            continue
        out.append(i)
    return out
