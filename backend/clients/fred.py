"""FRED API client — St. Louis Fed Economic Data.

Miễn phí 120 req/phút với API key.
  - fetch_series: lấy dữ liệu lịch sử cho macro score
  - fetch_upcoming_releases: lịch phát hành dữ liệu kinh tế tương lai
"""
import logging
from datetime import datetime, timedelta, timezone

from aiolimiter import AsyncLimiter

from clients.http_client import shared_client
from core.config import settings

log = logging.getLogger(__name__)

API_URL          = "https://api.stlouisfed.org/fred/series/observations"
RELEASES_API_URL = "https://api.stlouisfed.org/fred/releases/dates"

# 120 req/phút theo chính sách FRED — dùng 60 để safe.
_fred_rl = AsyncLimiter(max_rate=60, time_period=60)

# Các series dùng để tính macro sentiment cho crypto.
# Trend tăng/giảm của mỗi series được map sang positive/negative theo
# ý nghĩa KINH TẾ cho risk asset (crypto).
SERIES: dict[str, dict] = {
    "CPIAUCSL": {
        "name": "CPI (US Inflation)",
        "direction": "down_positive",  # lạm phát giảm → tốt cho crypto
        "unit": "index",
    },
    "DFF": {
        "name": "Fed Funds Rate",
        "direction": "down_positive",  # lãi suất giảm → tốt cho crypto
        "unit": "%",
    },
    "DGS10": {
        "name": "US 10Y Treasury Yield",
        "direction": "down_positive",  # yield giảm → risk-on
        "unit": "%",
    },
    "DTWEXBGS": {
        "name": "US Dollar Index (Broad)",
        "direction": "down_positive",  # USD yếu → crypto tăng
        "unit": "index",
    },
    "UNRATE": {
        "name": "US Unemployment Rate",
        "direction": "up_positive",  # thất nghiệp cao → Fed dovish → tốt
        "unit": "%",
    },
}


# FRED release IDs → metadata cho lịch kinh tế sắp tới.
UPCOMING_RELEASES: dict[int, dict] = {
    10:  {"name": "CPI (Consumer Price Index)",          "impact": "High",   "series": "CPIAUCSL"},
    50:  {"name": "Employment Situation (NFP/UNRATE)",   "impact": "High",   "series": "UNRATE"},
    82:  {"name": "Personal Income & Outlays (PCE)",     "impact": "High",   "series": "PCE"},
    175: {"name": "FOMC Press Release",                  "impact": "High",   "series": "DFF"},
    18:  {"name": "PPI (Producer Price Index)",          "impact": "Medium", "series": None},
    53:  {"name": "Gross Domestic Product (GDP)",        "impact": "High",   "series": None},
}


async def fetch_upcoming_releases(days_ahead: int = 30) -> list[dict]:
    """Lấy lịch phát hành dữ liệu kinh tế tương lai từ FRED Releases API.

    Gọi `/fred/releases/dates` với cửa sổ [today, today+days_ahead].
    Lọc các release_id quan trọng (CPI, NFP, PCE, FOMC, PPI, GDP).
    Trả list[dict] sắp xếp ASC theo ngày. Trả [] nếu lỗi hoặc không có key.
    """
    if not settings.fred_api_key:
        log.warning("FRED_API_KEY chưa set — bỏ qua fetch_upcoming_releases")
        return []

    today     = datetime.now(tz=timezone.utc).date()
    end_date  = today + timedelta(days=days_ahead)
    client    = shared_client()
    params = {
        "api_key":    settings.fred_api_key,
        "file_type":  "json",
        "realtime_start": str(today),
        "realtime_end":   str(end_date),
        "sort_order": "asc",
        "limit":      200,
        "include_release_dates_with_no_data": "true",
    }
    async with _fred_rl:
        try:
            resp = await client.get(RELEASES_API_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning(f"FRED releases/dates lỗi: {e}")
            return []

    target_ids = set(UPCOMING_RELEASES)
    out: list[dict] = []
    seen: set[tuple] = set()  # (release_id, date) — dedupe

    for item in data.get("release_dates", []):
        rid  = int(item.get("release_id", 0))
        date = item.get("date", "")
        if rid not in target_ids or not date:
            continue
        key = (rid, date)
        if key in seen:
            continue
        seen.add(key)
        meta = UPCOMING_RELEASES[rid]
        out.append({
            "release_id": rid,
            "name":       meta["name"],
            "date":       date,
            "impact":     meta["impact"],
            "series":     meta["series"],
        })

    return out


async def fetch_series(series_id: str, limit: int = 12) -> list[dict]:
    """Lấy N observation gần nhất của 1 series. Trả list
    [{"date","value"}] sắp xếp DESC theo ngày. Trả [] nếu lỗi.
    """
    if not settings.fred_api_key:
        log.warning("FRED_API_KEY chưa set — bỏ qua fetch_series")
        return []

    client = shared_client()
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    async with _fred_rl:
        try:
            resp = await client.get(API_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning(f"FRED {series_id} lỗi: {e}")
            return []

    out: list[dict] = []
    for obs in data.get("observations", []):
        val_str = obs.get("value", ".")
        if val_str in (".", "", None):
            continue
        try:
            val = float(val_str)
        except ValueError:
            continue
        out.append({"date": obs.get("date"), "value": val})
    return out
