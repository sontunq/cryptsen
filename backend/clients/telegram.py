"""
Telegram Public Channel Scraper
================================
Lấy tin từ các kênh Telegram công khai qua trang preview t.me/s/<username>.
Không cần API key — chỉ cần username của kênh (phải là public channel).

Luồng dữ liệu:
  fetch_telegram_posts(coin)        → tin liên quan đến coin cụ thể
  fetch_telegram_news_for_coin(coin) → lọc bỏ tin thuần macro
  fetch_telegram_macro_news()        → chỉ lấy tin vĩ mô

Cache: mỗi channel cache 30 phút (CACHE_TTL), tránh overload t.me.
Phân trang: 2 trang × ~20 bài = ≤40 bài/channel/cycle.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import TypedDict

from clients.http_client import shared_client
from core.time import now_vn

log = logging.getLogger(__name__)

# ===========================================================================
# Channel Registry
# ===========================================================================
# Mỗi entry là một dict mô tả channel:
#   username : str  — định danh trên Telegram (t.me/s/<username>)
#   label    : str  — tên hiển thị thân thiện
#   lang     : str  — "en" | "vi" | "mixed"
#   focus    : str  — "crypto" | "macro" | "both"
#   priority : int  — 1 = cao nhất (tin ưu tiên hiển thị trước)
#
# Để thêm nguồn mới: append 1 dict vào CHANNEL_REGISTRY.
# ===========================================================================

class ChannelMeta(TypedDict):
    username: str
    label: str
    lang: str
    focus: str
    priority: int


CHANNEL_REGISTRY: list[ChannelMeta] = [
    # ── Crypto news tổng hợp (tiếng Anh) ─────────────────────────────────
    {
        "username": "news_crypto",
        "label":    "Crypto News",
        "lang":     "en",
        "focus":    "crypto",
        "priority": 1,
    },
    {
        "username": "cointelegraph",
        "label":    "Cointelegraph",
        "lang":     "en",
        "focus":    "crypto",
        "priority": 1,
    },
    {
        "username": "coindesk",
        "label":    "CoinDesk",
        "lang":     "en",
        "focus":    "both",
        "priority": 1,
    },
    {
        "username": "WatcherGuru",
        "label":    "Watcher Guru",
        "lang":     "en",
        "focus":    "crypto",
        "priority": 2,
    },
    # ── On-chain & thị trường (tiếng Anh) ────────────────────────────────
    {
        "username": "WuBlockchain",
        "label":    "Wu Blockchain",
        "lang":     "en",
        "focus":    "both",
        "priority": 1,
    },
    {
        "username": "unfolded",
        "label":    "Unfolded (on-chain)",
        "lang":     "en",
        "focus":    "both",
        "priority": 2,
    },
    # ── Macro kinh tế toàn cầu (tiếng Anh) ───────────────────────────────
    {
        "username": "CryptoNewsFlash",
        "label":    "Crypto News Flash",
        "lang":     "en",
        "focus":    "both",
        "priority": 2,
    },
    # ── Cộng đồng Việt Nam ────────────────────────────────────────────────
    {
        "username": "coin68",
        "label":    "Coin68 (VN)",
        "lang":     "vi",
        "focus":    "crypto",
        "priority": 2,
    },
]

# Convenience: danh sách username để dùng trong gather()
TELEGRAM_CHANNELS: list[str] = [ch["username"] for ch in CHANNEL_REGISTRY]

# Map username → meta để tra nhanh khi cần label/focus
_CHANNEL_META: dict[str, ChannelMeta] = {
    ch["username"]: ch for ch in CHANNEL_REGISTRY
}


# ===========================================================================
# Macro keyword taxonomy
# ===========================================================================
# Bài chứa ít nhất 1 keyword dưới đây được phân loại vào feed Vĩ Mô.
# Tách thành nhóm để dễ bảo trì và mở rộng.
# ===========================================================================

_MACRO_KEYWORDS_MONETARY = [
    "fed", "fomc", "federal reserve", "interest rate", "rate cut", "rate hike",
    "monetary policy", "powell", "ecb", "boj", "pboc", "central bank",
    "quantitative easing", "qe", "quantitative tightening", "qt",
    "lãi suất", "ngân hàng trung ương", "chính sách tiền tệ",
]

_MACRO_KEYWORDS_INFLATION = [
    "cpi", "inflation", "deflation", "pce", "core inflation",
    "lạm phát",
]

_MACRO_KEYWORDS_ECONOMY = [
    "gdp", "unemployment", "payroll", "nfp", "jobs report",
    "recession", "economic growth", "fiscal policy",
    "kinh tế", "thất nghiệp",
]

_MACRO_KEYWORDS_MARKET = [
    "treasury", "yield", "dxy", "dollar index",
    "s&p", "nasdaq", "stock market", "global market",
    "risk-off", "risk-on",
]

_MACRO_KEYWORDS_GEOPOLITICAL = [
    "tariff", "trade war", "sanction", "geopolitical",
    "g7", "g20", "imf", "world bank",
    "thuế quan", "chiến tranh thương mại",
]

# Gộp tất cả thành 1 set để tra nhanh O(1)
_MACRO_KEYWORDS: frozenset[str] = frozenset(
    _MACRO_KEYWORDS_MONETARY
    + _MACRO_KEYWORDS_INFLATION
    + _MACRO_KEYWORDS_ECONOMY
    + _MACRO_KEYWORDS_MARKET
    + _MACRO_KEYWORDS_GEOPOLITICAL
)


# ===========================================================================
# Coin alias map — matching trong nội dung Telegram
# ===========================================================================
# Dùng lowercase. Thêm alias ngắn vào _AMBIGUOUS_TG nếu dễ false-positive.
# ===========================================================================

_TG_ALIASES: dict[str, list[str]] = {
    "BTC":  ["bitcoin", "btc", "₿"],
    "ETH":  ["ethereum", "ether", "eth"],
    "SOL":  ["solana", "sol"],
    "BNB":  ["binance coin", "bnb"],
    "XRP":  ["ripple", "xrp"],
    "ADA":  ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"],
    "AVAX": ["avalanche", "avax"],
    "DOT":  ["polkadot", "dot"],
    "MATIC":["polygon", "matic"],
    "LINK": ["chainlink", "link"],
    "LTC":  ["litecoin", "ltc"],
    "TRX":  ["tron", "trx"],
    "SHIB": ["shiba", "shib", "shiba inu"],
    "TON":  ["toncoin", "ton"],
    "NEAR": ["near protocol", "near"],
    "UNI":  ["uniswap", "uni"],
    "ARB":  ["arbitrum", "arb"],
    "OP":   ["optimism"],
    "SUI":  ["sui"],
    "APT":  ["aptos", "apt"],
    "INJ":  ["injective", "inj"],
    "SEI":  ["sei"],
    "TIA":  ["celestia", "tia"],
    "ATOM": ["cosmos", "atom"],
    "FTM":  ["fantom", "ftm"],
}

# Các ký hiệu ngắn / phổ biến → dễ false-positive → BẮT BUỘC match alias
_AMBIGUOUS_TG: frozenset[str] = frozenset({
    "LINK", "NEAR", "ONE", "GAS", "OP", "TON", "SEI", "FTM",
})


# ===========================================================================
# HTML parsing utilities
# ===========================================================================

_RE_TAG   = re.compile(r"<[^>]+>")
_RE_SPACE = re.compile(r"\s+")

# Regex tái sử dụng cho _parse_channel_html (compile 1 lần)
_MSG_PATTERN = re.compile(
    r'<div[^>]+class="[^"]*tgme_widget_message[^"]*"[^>]+'
    r'data-post="([^"]+)"[^>]*>(.*?)'
    r'(?=<div[^>]+class="[^"]*tgme_widget_message[^"]*"[^>]+data-post=|$)',
    re.DOTALL,
)
_TEXT_PATTERN = re.compile(
    r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_TIME_PATTERN  = re.compile(r'<time[^>]+datetime="([^"]+)"', re.DOTALL)
_VIEWS_PATTERN = re.compile(
    r'<span[^>]+class="[^"]*tgme_widget_message_views[^"]*"[^>]*>([^<]+)</span>',
    re.DOTALL,
)

# Nguồn ưu tiên cao được boost lên đầu trong feed (priority=1)
_PRIORITY_USERNAMES: frozenset[str] = frozenset(
    ch["username"] for ch in CHANNEL_REGISTRY if ch["priority"] == 1
)


# ===========================================================================
# Per-channel in-memory cache
# ===========================================================================

CACHE_TTL = 1800  # giây — 30 phút
_chan_cache: dict[str, tuple[float, list[dict]]] = {}
_chan_locks: dict[str, asyncio.Lock]             = {}


# ===========================================================================
# Internal helpers
# ===========================================================================

def _parse_views(raw: str) -> int:
    """'1.2K' → 1200 | '3.4M' → 3_400_000 | '320' → 320."""
    raw = raw.strip().upper().replace(",", "")
    try:
        if raw.endswith("K"):
            return int(float(raw[:-1]) * 1_000)
        if raw.endswith("M"):
            return int(float(raw[:-1]) * 1_000_000)
        return int(raw)
    except (ValueError, TypeError):
        return 0


def _strip_html(html: str) -> str:
    """Xóa thẻ HTML và chuẩn hóa khoảng trắng."""
    text = _RE_TAG.sub(" ", html)
    text = unescape(text)
    return _RE_SPACE.sub(" ", text).strip()


def _parse_channel_html(html: str, channel: str) -> list[dict]:
    """Parse HTML trang t.me/s/<channel> → list post dicts.

    Mỗi dict có các key:
        id           : str  — post ID (số)
        title        : str  — 300 ký tự đầu nội dung (dùng cho matching)
        body         : str  — 500 ký tự đầu (dùng cho analysis)
        url          : str  — link trực tiếp đến bài
        channel      : str  — username của channel
        channel_label: str  — tên hiển thị của channel
        views        : int  — lượt xem
        published_at : datetime (timezone-aware UTC)
        priority     : int  — 1 = cao, 2 = thường
    """
    meta    = _CHANNEL_META.get(channel, {})
    label   = meta.get("label", channel)
    priority = meta.get("priority", 2)
    posts: list[dict] = []

    for m in _MSG_PATTERN.finditer(html):
        data_post  = m.group(1)   # e.g. "cointelegraph/12345"
        bubble_html = m.group(2)

        # ── Text content ─────────────────────────────────────────────────
        text_m = _TEXT_PATTERN.search(bubble_html)
        if not text_m:
            continue  # bỏ post chỉ có media
        raw_text = _strip_html(text_m.group(1))
        if len(raw_text) < 15:
            continue  # quá ngắn, không có giá trị

        # ── Datetime ─────────────────────────────────────────────────────
        time_m = _TIME_PATTERN.search(bubble_html)
        if not time_m:
            continue
        try:
            pub = datetime.fromisoformat(time_m.group(1))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        # ── Views ────────────────────────────────────────────────────────
        views_m = _VIEWS_PATTERN.search(bubble_html)
        views   = _parse_views(views_m.group(1)) if views_m else 0

        # ── URL ──────────────────────────────────────────────────────────
        post_id = data_post.split("/")[-1] if "/" in data_post else ""
        url     = f"https://t.me/{channel}/{post_id}" if post_id else ""
        if not url:
            continue

        posts.append({
            "id":            post_id,
            "title":         raw_text[:300],
            "body":          raw_text[:500],
            "url":           url,
            "channel":       channel,
            "channel_label": label,
            "views":         views,
            "published_at":  pub,
            "priority":      priority,
        })

    return posts


async def _fetch_channel_html(channel: str, before_id: int | None = None) -> str | None:
    """GET t.me/s/<channel>[?before=<id>]. Trả HTML string hoặc None nếu lỗi."""
    url = f"https://t.me/s/{channel}"
    if before_id:
        url += f"?before={before_id}"

    client = shared_client()
    try:
        resp = await client.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text
        log.warning("Telegram %s → HTTP %s", channel, resp.status_code)
        return None
    except Exception as exc:
        log.warning("Telegram %s fetch error: %r", channel, exc)
        return None


async def _get_channel_posts(channel: str) -> list[dict]:
    """Lấy ≤40 bài trong 24h của 1 channel. Kết quả cache CACHE_TTL giây.

    Chiến lược phân trang:
      • Trang 1: 20 bài mới nhất.
      • Trang 2: tiếp tục từ post_id nhỏ nhất trang 1 (before=<min_id>).
    """
    now_ts = time.monotonic()
    cached = _chan_cache.get(channel)
    if cached and now_ts - cached[0] < CACHE_TTL:
        return cached[1]

    lock = _chan_locks.setdefault(channel, asyncio.Lock())
    async with lock:
        # Double-check sau khi acquire lock
        now_ts = time.monotonic()
        cached = _chan_cache.get(channel)
        if cached and now_ts - cached[0] < CACHE_TTL:
            return cached[1]

        cutoff    = now_vn() - timedelta(hours=24)
        all_posts: list[dict] = []
        seen_urls: set[str]   = set()

        def _add_if_recent(posts_batch: list[dict]) -> None:
            for p in posts_batch:
                if p["url"] in seen_urls:
                    continue
                if p["published_at"].astimezone(cutoff.tzinfo) <= cutoff:
                    continue
                all_posts.append(p)
                seen_urls.add(p["url"])

        # Trang 1
        html1 = await _fetch_channel_html(channel)
        if html1:
            _add_if_recent(_parse_channel_html(html1, channel))

            # Trang 2 — chỉ nếu trang 1 có bài hợp lệ
            if all_posts:
                try:
                    min_id = min(
                        int(p["id"]) for p in all_posts if p["id"].isdigit()
                    )
                    html2 = await _fetch_channel_html(channel, before_id=min_id)
                    if html2:
                        _add_if_recent(_parse_channel_html(html2, channel))
                except Exception as exc:
                    log.warning("Telegram %s page-2 error: %s", channel, exc)

        # Sắp xếp: priority=1 lên trước, rồi mới theo thời gian mới nhất
        all_posts.sort(
            key=lambda p: (p["priority"], -p["published_at"].timestamp())
        )

        _chan_cache[channel] = (time.monotonic(), all_posts)
        log.info("Telegram [%s] fetched %d posts (24h)", channel, len(all_posts))
        return all_posts


# ===========================================================================
# Coin-match logic
# ===========================================================================

def _matches_coin_tg(post: dict, symbol: str) -> bool:
    """True nếu post đề cập đến `symbol`.

    Độ ưu tiên match (từ cao đến thấp):
      1. Cashtag $symbol  — rất chính xác
      2. Alias với word-boundary nếu alias ≥5 ký tự (e.g. "bitcoin")
      3. Symbol ticker với word-boundary nếu không phải ambiguous
    """
    blob   = f"{post.get('title', '')} {post.get('body', '')}".lower()
    sym_l  = symbol.lower()
    aliases = _TG_ALIASES.get(symbol.upper(), [])

    # 1. $btc, $eth ...
    if f"${sym_l}" in blob:
        return True

    # 2. Ambiguous hoặc ticker ngắn → chỉ match qua alias dài (cần word boundary)
    if len(sym_l) <= 2 or symbol.upper() in _AMBIGUOUS_TG:
        return any(
            re.search(rf"\b{re.escape(a)}\b", blob)
            for a in aliases if len(a) >= 4
        )

    # 3. Ticker dài (≥3 ký tự) → word-boundary
    if re.search(rf"\b{re.escape(sym_l)}\b", blob):
        return True

    # 4. Alias match (luôn dùng word boundary để an toàn)
    for alias in aliases:
        if re.search(rf"\b{re.escape(alias)}\b", blob):
            return True

    return False


def _is_macro_post(post: dict) -> bool:
    """True nếu nội dung post thuộc chủ đề vĩ mô kinh tế."""
    blob = f"{post.get('title', '')} {post.get('body', '')}".lower()
    return any(kw in blob for kw in _MACRO_KEYWORDS)


# ===========================================================================
# Public API
# ===========================================================================

async def fetch_telegram_posts(coin_symbol: str) -> list[dict]:
    """Trả list post trong 24h có nhắc đến `coin_symbol` từ mọi channel.

    Fetch tất cả channel song song (asyncio.gather). Kết quả đã được
    sắp xếp: channel priority=1 trước, sau đó theo thời gian mới nhất.
    """
    cutoff = now_vn() - timedelta(hours=24)
    feeds  = await asyncio.gather(
        *(_get_channel_posts(ch) for ch in TELEGRAM_CHANNELS),
        return_exceptions=True,
    )
    matched: list[dict] = []
    for feed in feeds:
        if isinstance(feed, BaseException) or not feed:
            continue
        for p in feed:
            if p["published_at"].astimezone(cutoff.tzinfo) <= cutoff:
                continue
            if _matches_coin_tg(p, coin_symbol):
                matched.append(p)

    # Deduplicate theo URL (có thể bài được đăng lại trên nhiều channel)
    seen: set[str] = set()
    deduped: list[dict] = []
    for p in matched:
        if p["url"] not in seen:
            deduped.append(p)
            seen.add(p["url"])

    deduped.sort(key=lambda p: (p["priority"], -p["published_at"].timestamp()))
    return deduped


async def fetch_telegram_news_for_coin(coin_symbol: str) -> list[dict]:
    """Tin Telegram về coin — loại bỏ bài thuần vĩ mô.

    Dùng cho tab "Tin Tức" của trang chi tiết coin.
    """
    all_matched = await fetch_telegram_posts(coin_symbol)
    return [p for p in all_matched if not _is_macro_post(p)]


async def fetch_telegram_macro_news() -> list[dict]:
    """Tin Telegram vĩ mô kinh tế trong 24h — không lọc theo coin.

    Dùng cho tab "Vĩ Mô" / macro feed.
    Ưu tiên bài từ channel có focus="macro" hoặc "both".
    """
    cutoff      = now_vn() - timedelta(hours=24)
    macro_focus = frozenset(
        ch["username"]
        for ch in CHANNEL_REGISTRY
        if ch["focus"] in ("macro", "both")
    )

    feeds = await asyncio.gather(
        *(_get_channel_posts(ch) for ch in TELEGRAM_CHANNELS),
        return_exceptions=True,
    )

    macro_posts: list[dict] = []
    seen_urls: set[str]     = set()

    for feed in feeds:
        if isinstance(feed, BaseException) or not feed:
            continue
        for p in feed:
            if p["published_at"].astimezone(cutoff.tzinfo) <= cutoff:
                continue
            if p["url"] in seen_urls:
                continue
            if not _is_macro_post(p):
                continue
            # Boost bài từ channel chuyên về macro/both
            p = {**p, "priority": 1 if p["channel"] in macro_focus else p["priority"]}
            macro_posts.append(p)
            seen_urls.add(p["url"])

    macro_posts.sort(key=lambda p: (p["priority"], -p["published_at"].timestamp()))
    log.info("Telegram macro posts: %d bài (24h)", len(macro_posts))
    return macro_posts


def get_channel_registry() -> list[ChannelMeta]:
    """Trả danh sách metadata của tất cả channel đang active."""
    return CHANNEL_REGISTRY.copy()
