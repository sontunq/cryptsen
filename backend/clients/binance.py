import asyncio
import logging
import re
import time

from clients.http_client import shared_client
from core.config import settings
from core.time import format_vn, now_utc
from repositories import coin_repo

log = logging.getLogger(__name__)

# Cache CoinGecko image map theo symbol để tránh gọi lại nếu job
# chạy liên tiếp (6h interval nên thực tế không cần, nhưng an toàn hơn).
_CG_IMAGE_CACHE: dict[str, str] = {}
_CG_IMAGE_CACHE_TS: float = 0.0
_CG_IMAGE_CACHE_TTL = 3600 * 4  # 4 giờ


async def _fetch_coingecko_symbol_images() -> dict[str, str]:
    """Fetch symbol→image_url map từ CoinGecko markets (top 1000 coin).

    - Lấy 4 trang × 250 coin, sắp xếp theo market_cap_desc.
    - Chỉ lấy URL nhỏ (thumb) để tránh timeout — backend chỉ lưu URL,
      browser tự load hình sau.
    - Hàm chịu lỗi: nếu CoinGecko rate-limit hoặc down, trả dict rỗng.
    """
    global _CG_IMAGE_CACHE, _CG_IMAGE_CACHE_TS
    now_ts = time.monotonic()
    if _CG_IMAGE_CACHE and now_ts - _CG_IMAGE_CACHE_TS < _CG_IMAGE_CACHE_TTL:
        return _CG_IMAGE_CACHE

    client = shared_client()
    symbol_to_image: dict[str, str] = {}

    for page in range(1, 5):  # 4 pages × 250 = 1000 coins
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": "false",
                },
                timeout=15,
            )
            if resp.status_code == 429:
                log.warning(f"CoinGecko rate-limited khi fetch images (page {page})")
                break
            if not resp.is_success:
                log.warning(
                    f"CoinGecko images page {page} trả HTTP {resp.status_code}"
                )
                break
            data = resp.json() or []
            for coin in data:
                sym = str(coin.get("symbol") or "").upper()
                # Ưu tiên 'large' > 'small' > 'thumb' — dùng gì có
                image = (
                    str(coin.get("image") or "").strip()
                )
                if sym and image and sym not in symbol_to_image:
                    symbol_to_image[sym] = image
            if len(data) < 250:
                break  # hết data
            # Giãn cách nhỏ để không bị rate-limit
            await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"CoinGecko image fetch thất bại (page {page}): {e}")
            break

    if symbol_to_image:
        _CG_IMAGE_CACHE = symbol_to_image
        _CG_IMAGE_CACHE_TS = now_ts
        log.info(f"CoinGecko image cache: {len(symbol_to_image)} symbols")
    return symbol_to_image

_FUTURES_FUNDING_CACHE_TTL = 60
_futures_funding_cache: dict[str, object] = {"ts": 0.0, "rates": {}}
_SPOT_TICKER_CACHE_TTL = 60
_spot_ticker_cache: dict[str, object] = {"ts": 0.0, "rows": []}
_SPOT_QUOTES = ("USDT", "FDUSD", "USDC", "TUSD", "BUSD")
_BASE_RE = re.compile(r"^[A-Z0-9]{2,15}$")


def _is_valid_base_asset(base_asset: str) -> bool:
    """Loại token đòn bẩy/fiat pair để giữ danh sách coin spot cốt lõi."""
    if not base_asset:
        return False
    upper = base_asset.upper()
    if not _BASE_RE.match(upper):
        return False
    if upper.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return False
    if upper in {"USD", "EUR", "TRY", "RUB", "BRL", "UAH", "BIDR"}:
        return False
    return True


async def fetch_top_volume_coins(limit: int | None = None) -> list[dict]:
    """Đồng bộ coin theo top quoteVolume USDT 24h trên Binance Spot.

    Trả về list coin đã chọn (không phải JSON gốc từ Binance).
    """
    top_n = max(100, int(limit or settings.binance_top_coins))
    try:
        resp = await shared_client().get(
            "https://api.binance.com/api/v3/ticker/24hr", timeout=12
        )
        resp.raise_for_status()
        rows = resp.json() or []
    except Exception as e:
        log.exception(f"fetch_top_volume_coins failed: {e}")
        return []

    usdt_pairs: list[dict] = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if not _is_valid_base_asset(base):
            continue
        try:
            qv = float(r.get("quoteVolume") or 0.0)
        except Exception:
            qv = 0.0
        usdt_pairs.append(
            {
                "id": base.lower(),
                "symbol": base,
                "name": base,
                "image": "",
                "rank": 0,
                "quote_volume": qv,
            }
        )

    usdt_pairs.sort(key=lambda x: x.get("quote_volume", 0.0), reverse=True)
    selected = usdt_pairs[:top_n]
    for idx, c in enumerate(selected, start=1):
        c["rank"] = idx

    # Enrich với image URL từ CoinGecko — các coin đến từ Binance không
    # có trường image; hàm này bổ sung để frontend hiển thị logo đúng.
    try:
        cg_images = await _fetch_coingecko_symbol_images()
        if cg_images:
            enriched = 0
            for c in selected:
                if not c.get("image"):
                    img = cg_images.get(c["symbol"], "")
                    if img:
                        c["image"] = img
                        enriched += 1
            log.info(f"CoinGecko enrich: {enriched}/{len(selected)} coin có image mới")
    except Exception as e:
        log.warning(f"CoinGecko enrich thất bại (non-fatal): {e}")

    try:
        n = await coin_repo.upsert_many_ranked_by_symbol(selected)
        log.info(
            f"[{format_vn(now_utc())}] Binance top-volume: upsert {n}/{len(selected)} coin"
        )
    except Exception as e:
        log.exception(f"coin_repo.upsert_many_ranked_by_symbol failed: {e}")
    return selected


async def _fetch_all_futures_funding() -> dict[str, float]:
    """Fetch all futures funding rates to cache them."""
    now_ts = time.monotonic()
    cached_rates = _futures_funding_cache.get("rates", {})
    cached_ts = float(_futures_funding_cache.get("ts", 0.0))
    if cached_rates and now_ts - cached_ts < _FUTURES_FUNDING_CACHE_TTL:
        return cached_rates

    client = shared_client()
    try:
        resp = await client.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            timeout=12,
        )
        resp.raise_for_status()
        rows = resp.json() or []
        rates = {}
        for r in rows:
            sym = r.get("symbol", "")
            if sym.endswith("USDT"):
                base = sym[:-4]
                try:
                    rates[base] = float(r.get("lastFundingRate", 0))
                except ValueError:
                    pass
        
        _futures_funding_cache["ts"] = now_ts
        _futures_funding_cache["rates"] = rates
        return rates
    except Exception as e:
        log.warning(f"Futures premiumIndex error: {e}")
        return cached_rates


async def fetch_funding_score(symbol: str) -> float | None:
    """Futures funding rate score đo cảm xúc thị trường.

    Trả 0–10 nếu có data, None nếu không có hợp đồng Futures USDT.
    Điểm > 5: Funding dương (phe Long áp đảo, thị trường hưng phấn/tích cực).
    Điểm < 5: Funding âm (phe Short áp đảo, thị trường bi quan/tiêu cực).
    """
    sym = symbol.upper()
    rates = await _fetch_all_futures_funding()
    if sym not in rates:
        return None

    funding_rate = rates[sym]
    # Scale thuận chiều cảm xúc: 0 -> 5, +0.001 -> 7.5, -0.001 -> 2.5
    score = 5 + (funding_rate * 2500)
    return round(max(0.0, min(10.0, score)), 2)
