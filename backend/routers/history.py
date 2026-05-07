"""Endpoint trả lịch sử sentiment từ CSV để frontend vẽ biểu đồ backtest."""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from storage.csv_logger import sentiment_logger

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["history"])


def _parse_ts(raw: str) -> datetime | None:
    try:
        # Format ghi ra: 2026-04-20T04:30:00Z
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        # Fallback ISO 8601 tổng quát.
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None


@router.get("/history")
async def get_history(
    symbol: str | None = Query(default=None),
    source: str | None = Query(
        default=None, pattern="^(news|macro|social|funding)$"
    ),
    hours: int = Query(default=24, ge=1, le=24 * 30),
):
    """Đọc ngược history CSV (file hiện tại + archive), lọc trong `hours` giờ gần nhất.

    Dừng quét sớm khi gặp dòng timestamp cũ hơn ngưỡng để tiết kiệm I/O
    (mỗi file được ghi tuần tự theo thời gian nên đọc ngược là monotonic).
    """
    paths = sentiment_logger.history_paths()
    if not paths:
        return {"items": [], "count": 0, "hours": hours}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    symbol_filter = symbol.upper() if symbol else None
    items: list[dict] = []

    try:
        # Đọc từ file mới nhất -> cũ nhất để có thể break sớm theo cutoff.
        stop_all = False
        for path in reversed(paths):
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            for row in reversed(rows):
                ts = _parse_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                if ts < cutoff:
                    stop_all = True
                    break
                if symbol_filter and row.get("symbol", "").upper() != symbol_filter:
                    continue
                if source and row.get("source") != source:
                    continue
                try:
                    score_val = float(row.get("sentiment_score") or 0.0)
                except ValueError:
                    score_val = 0.0
                items.append(
                    {
                        "timestamp": row.get("timestamp"),
                        "symbol": row.get("symbol"),
                        "source": row.get("source"),
                        "sentiment_label": row.get("sentiment_label") or None,
                        "sentiment_score": score_val,
                    }
                )

            if stop_all:
                break
    except Exception as e:
        log.exception(f"đọc sentiment history CSV lỗi: {e}")
        raise HTTPException(status_code=500, detail="Không đọc được lịch sử")

    # Trả theo thứ tự thời gian tăng dần để FE vẽ chart dễ.
    items.reverse()
    return {
        "items": items,
        "count": len(items),
        "hours": hours,
        "symbol": symbol_filter,
        "source": source,
    }
