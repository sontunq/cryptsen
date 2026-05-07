import asyncio
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone

import xml.etree.ElementTree as ET

from aiolimiter import AsyncLimiter

from clients.http_client import shared_client
from core.config import settings
from core.time import now_vn

log = logging.getLogger(__name__)

# Subreddit chuyên về crypto chung / thị trường — ĐƯỢC PHÉP chứa bài vĩ mô/chính trị
# Không bao gồm sub chất lượng thấp (MoonShots, SatoshiStreetBets)
SUBREDDITS_GENERAL = [
    "CryptoCurrency",
    "CryptoMarkets",
    "investing",
]

# Subreddit tin tức/kinh tế thế giới — chỉ lấy bài có liên quan vĩ mô
SUBREDDITS_MACRO = [
    "worldnews",
    "Economics",
    "finance",
    "business",
    "geopolitics",
]

# Subreddit coin-specific (dùng tên coin làm từ khoá tìm kiếm chính)
SUBREDDITS_COIN = [
    "Bitcoin",
    "ethereum",
    "altcoin",
    "binance",
]

# Toàn bộ subreddit sẽ được cào (dùng cho _get_sub_feed)
SUBREDDITS = SUBREDDITS_GENERAL + SUBREDDITS_MACRO + SUBREDDITS_COIN

# Reddit WAF fingerprint:
# - /r/{sub}/search.rss?restrict_sr=1 → trả feed rỗng (bug phía Reddit).
# - Header `Accept` tường minh → 403.
# - UA "python-requests" / "compatible; ..." → 403/429.
# Cách đi ổn định: /r/{sub}/new.json (KHÔNG Accept, UA browser), filter coin
# client-side, phân trang `?after=<fullname>` tới khi bài vượt cutoff 24h.
_reddit_rl = AsyncLimiter(max_rate=20, time_period=60)

_CACHE_TTL = 1800       # 30 phút — bằng tier1 interval
_SEARCH_CACHE_TTL = 1200  # 20 phút cho search results (cần fresh hơn RSS)

# Cache ở cấp subreddit: sub -> (monotonic_ts, list[posts])
_sub_cache: dict[str, tuple[float, list[dict]]] = {}
# Cache search results: coin_symbol_lower -> (monotonic_ts, list[posts])
_search_cache: dict[str, tuple[float, list[dict]]] = {}

# Single-flight lock per sub: n coroutine tier1 song song cùng trỏ vào
# 1 sub cache-miss → chỉ 1 coroutine fetch, phần còn lại đợi rồi dùng
# cache luôn (tránh N× request cho cùng data).
_sub_locks: dict[str, asyncio.Lock] = {}
_search_locks: dict[str, asyncio.Lock] = {}

# Alias tên đầy đủ cho một số coin phổ biến để tăng recall khi filter title.
_NAME_ALIASES: dict[str, list[str]] = {
    # Symbol ngắn dễ nhiễu (vd "U") -> map alias rõ nghĩa để tránh match bừa.
    "U": ["usdt", "tether"],
    "BTC": ["bitcoin"],
    "ETH": ["ethereum", "ether"],
    "SOL": ["solana"],
    "BNB": ["binance coin"],
    "XRP": ["ripple"],
    "ADA": ["cardano"],
    "DOGE": ["dogecoin"],
    "AVAX": ["avalanche"],
    "DOT": ["polkadot"],
    "MATIC": ["polygon"],
    "LINK": ["chainlink"],
    "LTC": ["litecoin"],
    "TRX": ["tron"],
    "SHIB": ["shiba", "shiba inu"],
    "TON": ["toncoin"],
    "TAO": ["bittensor"],
    "FET": ["fetch.ai", "fetch ai"],
    "INJ": ["injective"],
    "SUI": ["sui network"],
    "APT": ["aptos"],
    "SEI": ["sei network"],
}

# Bảng coin symbol → tên đầy đủ, dùng để PHÁT HIỆN bài viết đề cập coin cụ thể
# (phục vụ relaxed-mode lọc tier 1/2). Chỉ cần độ chính xác cao, không cần
# recall đầy đủ — thiếu coin hiếm là chấp nhận được.
_COIN_NAME_PATTERNS: dict[str, list[str]] = {
    "btc":  ["bitcoin"],
    "eth":  ["ethereum", "ether"],
    "bnb":  ["binance coin", "binance smart chain"],
    "xrp":  ["ripple"],
    "sol":  ["solana"],
    "ada":  ["cardano"],
    "doge": ["dogecoin"],
    "avax": ["avalanche"],
    "dot":  ["polkadot"],
    "matic":["polygon"],
    "link": ["chainlink"],
    "ltc":  ["litecoin"],
    "trx":  ["tron"],
    "shib": ["shiba inu", "shiba"],
    "ton":  ["toncoin"],
    "tao":  ["bittensor"],
    "sui":  ["sui network"],
    "apt":  ["aptos"],
    "near": ["near protocol"],
    "atom": ["cosmos"],
    "uni":  ["uniswap"],
    "xlm":  ["stellar"],
    "inj":  ["injective"],
    "fet":  ["fetch.ai", "fetch ai"],
    "sei":  ["sei network"],
    "op":   ["optimism"],
    "arb":  ["arbitrum"],
    "fil":  ["filecoin"],
    "icp":  ["internet computer"],
    "hbar": ["hedera"],
    "etc":  ["ethereum classic"],
    "bch":  ["bitcoin cash"],
    "xmr":  ["monero"],
    "algo": ["algorand"],
    "ftm":  ["fantom"],
    "egld": ["elrond", "multiversx"],
    "theta":["theta network"],
    "vet":  ["vechain"],
    "sand": ["sandbox"],
    "mana": ["decentraland"],
    "axs":  ["axie infinity"],
    "grt":  ["the graph"],
}

# Một số ticker trùng từ phổ thông hoặc dễ gây nhiễu khi match theo word-boundary.
# Với các ticker này, chỉ cho phép cashtag ($LINK) hoặc tên coin rõ ràng.
_AMBIGUOUS_SYMBOLS = {
    "LINK",
    "NEAR",
    "ONE",
    "GAS",
    "OP",
    # 3-ký-tự dễ xuất hiện trong body RSS ngoài ngữ cảnh coin
    "TAO",  # "tao" = từ tiếng Việt / triết học Taoism
    "FET",  # "fet" khớp nhiều tên biến/kỹ thuật
    "SUI",  # "sui" = tiếng Nhật/Ý
    "SEI",  # "sei" = tiếng Nhật
    "APT",  # "apt" = tính từ tiếng Anh
}

# Các mẫu "chuyện phiếm" thường không hữu ích cho sentiment coin.
_LOW_QUALITY_TITLE_PATTERNS = [
    r"^daily\s+discussion",
    r"^beginner\s+question",
    r"^weekly\s+thread",
    r"^how\s+to\b",
    r"^what\s+is\b",
    r"^can\s+i\b",
    r"^lost\b",
    r"^help\b",
    r"^eli5\b",
    r"^question\b",
    r"^rant\b",
    r"^vent\b",
    r"bought\s+\w+\s+at",      # "bought X at $Y" — chuyện cá nhân
    r"\bmy\s+(first|portfolio)\b",
    r"\bi\s+(lost|gained|made|bought|sold)\b",
]

# Keyword ngữ cảnh thị trường để tăng precision cho symbol mơ hồ.
_CRYPTO_CONTEXT_KEYWORDS = {
    "coin",
    "token",
    "crypto",
    "market",
    "price",
    "bull",
    "bear",
    "trade",
    "trading",
    "volume",
    "futures",
    "spot",
    "etf",
    "on-chain",
    "whale",
    "support",
    "resistance",
    "breakout",
    "pump",
    "dump",
    "stablecoin",
    "defi",
}

# Keyword vĩ mô / chính trị ảnh hưởng thị trường — dùng để lọc bài "crypto chung"
# và bài từ subreddit macro (worldnews, Economics, finance).
# Chia thành 2 nhóm để tránh false-positive:
#   _MACRO_KW_PHRASE : cụm từ dài (≥2 từ) — match an toàn bằng substring.
#   _MACRO_KW_WORD   : từ đơn/viết tắt ngắn — cần word-boundary (\b) để
#                      tránh match nhầm: "sec" ≠ "second", "ban" ≠ "band", v.v.
_MACRO_KW_PHRASE: list[str] = [
    # Kinh tế vĩ mô — cụm từ
    "interest rate", "federal reserve", "rate hike", "rate cut",
    "debt ceiling", "quantitative easing", "monetary policy",
    "trade war", "white house", "executive order",
    "stock market", "market crash", "bear market", "bull market",
    "hedge fund", "etf approval", "bitcoin etf", "spot etf",
    "crypto regulation", "crypto ban", "stablecoin law",
    "binance lawsuit", "coinbase lawsuit",
    "sec vs", "middle east", "risk-off", "risk-on",
    "s&p 500", "s&p",
]

_MACRO_KW_WORD: list[str] = [
    # Kinh tế vĩ mô — từ đơn
    "inflation", "fomc", "recession", "stagflation",
    "dxy", "dollar", "treasury", "bond", "yield",
    "tightening", "fiscal", "stimulus", "bailout", "bankrupt",
    "cpi", "gdp", "qe",
    # Chính trị / địa chính trị
    "trump", "biden", "congress", "senate", "election",
    "sanction", "tariff", "geopolitical",
    "russia", "china", "taiwan", "iran", "israel",
    "sec", "regulation", "lawsuit", "legislation", "policy",
    "nasdaq", "dow",
    # Thị trường tài chính
    "liquidity", "correlation", "institutional", "blackrock", "fidelity",
    # Sự kiện crypto vĩ mô
    "halving", "cbdc", "gensler", "ftx", "collapse",
]

# Pattern regex tổng hợp cho word-boundary (compile 1 lần để tái dùng)
_MACRO_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _MACRO_KW_WORD) + r")\b"
)


async def _fetch_rss(url: str, max_retry: int = 2) -> ET.Element | None:
    """Rate-limited fetch Reddit RSS XML.

    Sử dụng UA browser-like để bypass 403 block của Reddit.
    """
    client = shared_client()
    delay = 1.0
    for attempt in range(max_retry):
        async with _reddit_rl:
            try:
                # Randomize UA to avoid being blocked by WAF
                ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{110 + random.randint(0, 15)}.0.0.0 Safari/537.36"
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": ua,
                        "Connection": "close"
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    try:
                        return ET.fromstring(resp.text)
                    except Exception as e:
                        log.warning(f"Reddit XML parse lỗi {url}: {e!r}")
                        return None
                if resp.status_code in (403, 429):
                    log.warning(
                        f"Reddit {resp.status_code} {url} — retry sau {delay}s "
                        f"(attempt {attempt+1})"
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                log.warning(f"Reddit {resp.status_code} {url}")
                return None
            except Exception as e:
                log.warning(f"Reddit fetch exception {url}: {e!r}")
                return None
    return None


def _parse_rss(payload: ET.Element, sub: str) -> list[dict]:
    """Parse 1 trang RSS (Atom feed) của sub.
    """
    posts: list[dict] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = payload.findall("atom:entry", ns)
    for ent in entries:
        title = (ent.find("atom:title", ns).text or "").strip()
        link_elem = ent.find("atom:link", ns)
        url = link_elem.attrib.get("href", "") if link_elem is not None else ""
        content_elem = ent.find("atom:content", ns)
        raw_body = content_elem.text if content_elem is not None else ""
        
        # XML content là HTML -> dọn dẹp thẻ
        body = re.sub(r'<[^>]+>', ' ', raw_body)
        body = re.sub(r'\s+', ' ', body).strip()
        if len(body) > 500:
            body = body[:500]
            
        pub_date_str = ent.find("atom:updated", ns).text if ent.find("atom:updated", ns) is not None else None
        if not pub_date_str:
            continue
        try:
            pub = datetime.fromisoformat(pub_date_str)
        except Exception:
            continue

        try:
            post_id = url.split("comments/")[1].split("/")[0] if "comments/" in url else ""
        except IndexError:
            post_id = ""

        posts.append(
            {
                "id": post_id,
                "title": title,
                "body": body,
                "url": url,
                "subreddit": sub,
                "upvotes": 0,    # RSS không có upvote trực tiếp, nhưng vì lấy top.rss nên coi như high-quality
                "num_comments": 0,
                "published_at": pub,
            }
        )
    return posts


async def _get_sub_feed(sub: str) -> list[dict]:
    """Lấy bài 24h qua của 1 sub (cache 30 phút) qua RSS top & hot để lấy content chất lượng.
    """
    # Fast path: cache hit, không cần lock.
    now_ts = time.monotonic()
    cached = _sub_cache.get(sub)
    if cached and now_ts - cached[0] < _CACHE_TTL:
        return cached[1]

    lock = _sub_locks.setdefault(sub, asyncio.Lock())
    async with lock:
        # Re-check sau khi acquire: coroutine trước có thể đã điền cache.
        now_ts = time.monotonic()
        cached = _sub_cache.get(sub)
        if cached and now_ts - cached[0] < _CACHE_TTL:
            return cached[1]

        cutoff = now_vn() - timedelta(hours=24)
        all_posts: list[dict] = []
        seen_urls = set()
        
        # Scrape từ nhiều luồng để tăng số lượng bài viết lấy được, tăng cơ hội tìm thấy bài Tích cực/Tiêu cực
        for feed_type in ["hot.rss", "top.rss?t=day", "new.rss", "rising.rss"]:
            url = f"https://www.reddit.com/r/{sub}/{feed_type}"
            payload = await _fetch_rss(url)
            if payload is not None:
                page_posts = _parse_rss(payload, sub)
                for p in page_posts:
                    if p["url"] not in seen_urls and p["published_at"].astimezone(cutoff.tzinfo) > cutoff:
                        all_posts.append(p)
                        seen_urls.add(p["url"])
                        
        _sub_cache[sub] = (time.monotonic(), all_posts)
        log.info(
            f"Reddit {sub}: fetched {len(all_posts)} bài qua RSS (top & hot)"
        )
        return all_posts


def _matches_coin(post: dict, symbol: str) -> bool:
    """Match coin trong title HOẶC body post.

    Hỗ trợ 3 pattern:
      1. Symbol whole-word: "BTC", "ETH" (regex \\b boundary, ≤4 ký tự
         tránh false-positive kiểu "ETH" trong "methods").
      2. Alias tên dài: "bitcoin", "ethereum" (substring).
      3. Cashtag kiểu Twitter: "$BTC" — match bất kể boundary vì dấu $
         đã phân tách rõ.
    """
    title = post.get("title", "")
    body = post.get("body", "")
    if not title and not body:
        return False
    # Gộp title + body để quét 1 lần. Lowercase một lần.
    blob = f"{title}\n{body}".lower()
    sym_l = symbol.lower()
    # Cashtag: $btc, $eth — match trực tiếp, không cần boundary.
    if f"${sym_l}" in blob:
        return True

    aliases = _NAME_ALIASES.get(symbol.upper(), [])

    # Symbol quá ngắn (1-2 ký tự) hoặc ticker dễ nhiễu (vd LINK) không nên
    # match theo word-boundary vì sẽ kéo nhầm các bài không liên quan.
    # Khi đó chỉ chấp nhận tên coin rõ ràng.
    if len(sym_l) <= 2 or symbol.upper() in _AMBIGUOUS_SYMBOLS:
        for alias in aliases:
            if alias in blob:
                return True
        return False

    if re.search(rf"\b{re.escape(sym_l)}\b", blob):
        return True

    for alias in aliases:
        if len(alias) <= 4:
            if re.search(rf"\b{re.escape(alias)}\b", blob):
                return True
        elif alias in blob:
            return True
    return False


def _find_mentioned_coins(blob: str) -> set[str]:
    """Trả tập symbol (lowercase) của các coin được nhắc rõ ràng trong blob.

    Chỉ tính là "đề cập" khi có:
      - Cashtag: $btc, $eth ... (chính xác cao)
      - Tên đầy đủ từ _COIN_NAME_PATTERNS: "bitcoin", "ethereum" ...
    Symbol ngắn không có cashtag bị bỏ qua để tránh false-positive.
    """
    found: set[str] = set()
    for sym, names in _COIN_NAME_PATTERNS.items():
        if f"${sym}" in blob:
            found.add(sym)
            continue
        for name in names:
            if name in blob:
                found.add(sym)
                break
    return found


def _is_macro_relevant(post: dict) -> bool:
    """Kiểm tra bài có liên quan đến vĩ mô/chính trị ảnh hưởng thị trường.

    Dùng 2 chiến lược tránh false-positive:
      - _MACRO_KW_PHRASE : cụm dài → match substring an toàn.
      - _MACRO_KW_WORD   : từ ngắn → match word-boundary (regex) để
        tránh "sec" khớp "second", "ban" khớp "band", v.v.
    Trả True nếu ít nhất 1 keyword nào đó match.
    Dùng để lọc:
      1. Bài "crypto chung" (không nhắc coin cụ thể) từ sub chung.
      2. Tất cả bài từ subreddit macro (worldnews, Economics, finance).
    """
    title = post.get("title", "")
    body = post.get("body", "")
    blob = f"{title}\n{body}".lower()
    # Kiểm tra cụm từ dài trước (nhanh hơn)
    if any(kw in blob for kw in _MACRO_KW_PHRASE):
        return True
    # Kiểm tra từ ngắn với word-boundary
    return bool(_MACRO_WORD_RE.search(blob))


def _is_relevant_relaxed(post: dict, coin_symbol: str) -> bool:
    """Logic mở rộng cho tier 1/2 (coin top 30) — ĐÃ THẮT CHẶT.

    Giữ lại bài nếu:
      - Nhắc đến coin này (có hoặc không có coin khác đi kèm), HOẶC
      - Không nhắc đến bất kỳ coin cụ thể nào VÀ có nội dung vĩ mô/chính trị
        thực sự ảnh hưởng thị trường.
    Loại bỏ:
      - Bài chỉ nhắc đến coin KHÁC mà không đề cập coin này.
      - Bài crypto chung mà chỉ là chuyện phiếm/cá nhân (không có macro keyword).
    """
    if _matches_coin(post, coin_symbol):
        return True

    title = post.get("title", "")
    body = post.get("body", "")
    blob = f"{title}\n{body}".lower()
    sym_l = coin_symbol.lower()

    mentioned = _find_mentioned_coins(blob)
    # Có coin được nhắc đến nhưng không phải coin này → loại
    if mentioned and sym_l not in mentioned:
        return False

    # Không có coin cụ thể nào → chỉ giữ nếu là tin vĩ mô/chính trị thực sự.
    # Tránh giữ chuyện phiếm kiểu "vc coins are the biggest scam",
    # "crypto is quietly becoming...", "bought SUSHI at $5.20...", v.v.
    return _is_macro_relevant(post)


def _is_quality_post(post: dict, symbol: str) -> bool:
    """Lọc bài chất lượng thấp để feed bớt nhiễu cho người dùng."""
    title = str(post.get("title") or "").strip()
    body = str(post.get("body") or "").strip()
    if not title:
        return False

    title_l = title.lower()
    for pat in _LOW_QUALITY_TITLE_PATTERNS:
        if re.search(pat, title_l):
            return False

    # Tiêu đề quá ngắn thường là câu hỏi rời rạc, khó mang tín hiệu sentiment.
    if len(title_l) < 10:
        return False

    # Với symbol ngắn mơ hồ, bắt buộc có ngữ cảnh crypto rõ ràng.
    if len(symbol.strip()) <= 2:
        blob = f"{title_l} {body.lower()}"
        if not any(k in blob for k in _CRYPTO_CONTEXT_KEYWORDS):
            return False

    return True


def _build_search_query(coin_symbol: str) -> str:
    """Xây query tối ưu cho Reddit Search API từ symbol + alias.

    Ưu tiên alias tên đầy đủ ("bitcoin") hơn symbol ngắn ("BTC") vì
    Reddit search match toàn văn — symbol ngắn dễ gây false-positive.
    Dùng OR để tăng recall, giới hạn 3 term để tránh query quá dài.
    """
    sym_upper = coin_symbol.upper()
    sym_lower = coin_symbol.lower()
    terms: list[str] = []

    # Ưu tiên alias tên đầy đủ
    aliases = _NAME_ALIASES.get(sym_upper, [])
    for alias in aliases[:2]:           # tối đa 2 alias
        terms.append(alias)

    # Thêm cashtag nếu symbol không quá ngắn/mơ hồ
    if len(sym_lower) >= 3 and sym_upper not in _AMBIGUOUS_SYMBOLS:
        terms.append(f"${sym_upper}")
    elif not terms:                     # fallback: symbol thường
        terms.append(sym_lower)

    return " OR ".join(terms) if terms else sym_lower


async def _search_reddit_json(coin_symbol: str) -> list[dict]:
    """Tìm kiếm bài Reddit 24h qua liên quan đến coin dùng search.json.

    Endpoint: https://www.reddit.com/search.json
    Không cần OAuth — dùng UA browser để tránh WAF.
    Trả [] nếu 403/429/lỗi (fallback im lặng, không crash pipeline).

    Cache 20 phút theo coin_symbol để tránh spam search endpoint.
    """
    sym_key = coin_symbol.lower()

    # Fast path: cache hit
    now_ts = time.monotonic()
    cached = _search_cache.get(sym_key)
    if cached and now_ts - cached[0] < _SEARCH_CACHE_TTL:
        return cached[1]

    lock = _search_locks.setdefault(sym_key, asyncio.Lock())
    async with lock:
        # Re-check sau acquire
        now_ts = time.monotonic()
        cached = _search_cache.get(sym_key)
        if cached and now_ts - cached[0] < _SEARCH_CACHE_TTL:
            return cached[1]

        query = _build_search_query(coin_symbol)
        cutoff = now_vn() - timedelta(hours=24)
        client = shared_client()
        posts: list[dict] = []

        # Thử lần lượt: search toàn Reddit → search trong r/CryptoCurrency (fallback)
        search_urls = [
            (
                "https://www.reddit.com/search.json",
                {"q": query, "sort": "new", "t": "day", "limit": "25", "type": "link"},
            ),
            (
                "https://www.reddit.com/r/CryptoCurrency/search.json",
                {"q": query, "sort": "new", "t": "day", "limit": "25",
                 "restrict_sr": "1", "type": "link"},
            ),
        ]

        for base_url, params in search_urls:
            try:
                ua = (
                    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    f"AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{110 + random.randint(0, 15)}.0.0.0 Safari/537.36"
                )
                async with _reddit_rl:
                    resp = await client.get(
                        base_url,
                        params=params,
                        headers={"User-Agent": ua, "Connection": "close"},
                        timeout=12,
                    )

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        children = data.get("data", {}).get("children", [])
                    except Exception as e:
                        log.warning(f"Reddit search JSON parse lỗi ({coin_symbol}): {e!r}")
                        continue

                    for child in children:
                        p = child.get("data", {})
                        title = (p.get("title") or "").strip()
                        if not title:
                            continue

                        created_utc = p.get("created_utc")
                        if not created_utc:
                            continue
                        try:
                            pub = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                        except Exception:
                            continue

                        if pub.astimezone(cutoff.tzinfo) <= cutoff:
                            continue  # quá cũ

                        permalink = p.get("permalink", "")
                        url = f"https://www.reddit.com{permalink}" if permalink else ""
                        post_id = p.get("id", "")
                        subreddit = p.get("subreddit", "")

                        # Lấy selftext (body) nếu có, cắt ngắn như RSS
                        body = (p.get("selftext") or "").strip()
                        if len(body) > 500:
                            body = body[:500]

                        posts.append({
                            "id": post_id,
                            "title": title,
                            "body": body,
                            "url": url,
                            "subreddit": subreddit,
                            "upvotes": int(p.get("ups") or 0),
                            "num_comments": int(p.get("num_comments") or 0),
                            "published_at": pub,
                        })

                    log.info(
                        f"Reddit search ({coin_symbol}): query={query!r} "
                        f"url={base_url} → {len(posts)} bài"
                    )
                    break   # thành công → không cần fallback

                elif resp.status_code in (403, 429):
                    log.warning(
                        f"Reddit search {resp.status_code} ({coin_symbol}) "
                        f"tại {base_url} — thử fallback"
                    )
                    await asyncio.sleep(1.5)
                    continue
                else:
                    log.warning(
                        f"Reddit search {resp.status_code} ({coin_symbol}) tại {base_url}"
                    )
                    break

            except Exception as e:
                log.warning(f"Reddit search exception ({coin_symbol}) {base_url}: {e!r}")
                continue

        _search_cache[sym_key] = (time.monotonic(), posts)
        return posts


async def fetch_matched_posts(
    coin_symbol: str, relaxed: bool = False
) -> list[dict]:
    """Trả list post 24h qua liên quan đến coin.

    Kết hợp 2 nguồn chạy song song:
      1. RSS feed theo subreddit (cache 30 phút) — coverage rộng.
      2. Reddit Search API search.json (cache 20 phút) — precision cao,
         tìm đúng tên coin, có upvote thật.
    Kết quả dedupe theo URL trước khi trả.

    relaxed=True (tier 1/2): bao gồm tin vĩ mô/chính trị chất lượng cao
    và bài nhắc đến coin này; loại bài về coin khác và chuyện phiếm.
    relaxed=False (tier 3/4): chỉ lấy bài nhắc đến coin này (strict match).
    """
    cutoff = now_vn() - timedelta(hours=24)

    # Chạy song song: RSS feeds + Search API
    rss_task = asyncio.gather(
        *(_get_sub_feed(s) for s in SUBREDDITS), return_exceptions=True
    )
    search_task = asyncio.create_task(_search_reddit_json(coin_symbol))
    feeds_results, search_posts = await asyncio.gather(
        rss_task, search_task, return_exceptions=True
    )

    if isinstance(search_posts, BaseException):
        log.warning(f"Reddit search task lỗi ({coin_symbol}): {search_posts}")
        search_posts = []

    # Tạo mapping subreddit → nhóm để áp dụng logic lọc đúng
    _macro_subs = {s.lower() for s in SUBREDDITS_MACRO}
    _coin_subs = {s.lower() for s in SUBREDDITS_COIN}

    matched: list[dict] = []
    seen_urls: set[str] = set()

    # ── Nguồn 1: RSS feeds theo subreddit ────────────────────────────────
    for sub, feed in zip(SUBREDDITS, feeds_results):
        if isinstance(feed, BaseException) or not feed:
            continue
        sub_lower = sub.lower()
        is_macro_sub = sub_lower in _macro_subs
        is_coin_sub = sub_lower in _coin_subs

        for p in feed:
            if p["published_at"].astimezone(cutoff.tzinfo) <= cutoff:
                continue
            if not _is_quality_post(p, coin_symbol):
                continue

            keep = False
            if is_macro_sub:
                if _is_macro_relevant(p) and _matches_coin(p, coin_symbol):
                    keep = True
                elif _is_macro_relevant(p) and relaxed:
                    title = p.get("title", "")
                    body = p.get("body", "")
                    blob = f"{title}\n{body}".lower()
                    if any(k in blob for k in _CRYPTO_CONTEXT_KEYWORDS):
                        mentioned = _find_mentioned_coins(blob)
                        if not mentioned:
                            keep = True
            elif is_coin_sub:
                keep = _matches_coin(p, coin_symbol)
            else:
                if relaxed:
                    keep = _is_relevant_relaxed(p, coin_symbol)
                else:
                    keep = _matches_coin(p, coin_symbol)

            if keep:
                url = p.get("url", "")
                if url not in seen_urls:
                    matched.append(p)
                    seen_urls.add(url)

    # ── Nguồn 2: Search API — strict match (đã tìm đúng tên coin) ────────
    for p in search_posts:
        if not _is_quality_post(p, coin_symbol):
            continue
        # Search results đã target đúng coin → chỉ cần loại bài về coin khác
        if not _matches_coin(p, coin_symbol):
            # Cho phép bài macro chung nếu relaxed (không nhắc coin cụ thể)
            if relaxed and _is_macro_relevant(p):
                mentioned = _find_mentioned_coins(
                    f"{p.get('title', '')}\n{p.get('body', '')}".lower()
                )
                if mentioned:
                    continue   # nhắc coin khác → bỏ
            else:
                continue

        url = p.get("url", "")
        if url and url not in seen_urls:
            matched.append(p)
            seen_urls.add(url)

    log.info(
        f"fetch_matched_posts ({coin_symbol}): "
        f"rss={len(matched) - len(search_posts)} "
        f"search={len([p for p in search_posts if p.get('url','') in seen_urls])} "
        f"total={len(matched)}"
    )
    return matched


async def count_reddit_mentions(
    coin_symbol: str, relaxed: bool = False
) -> int:
    """Alias nhẹ trả số lượng match (tương thích gọi cũ)."""
    return len(await fetch_matched_posts(coin_symbol, relaxed=relaxed))


async def scrape_reddit(
    coin_symbol: str, limit: int = 20, relaxed: bool = False
) -> list[dict]:
    """Trả list bài 24h qua liên quan đến coin, mới nhất trước.

    Output item:
        {"id","title","body","url","subreddit","upvotes","num_comments",
         "published_at": datetime UTC aware}
    """
    matched = await fetch_matched_posts(coin_symbol, relaxed=relaxed)
    matched.sort(key=lambda p: p["published_at"], reverse=True)
    return matched[:limit]
