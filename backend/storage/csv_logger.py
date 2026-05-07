"""CSV logger cho lịch sử phân tích sentiment (phục vụ backtest đồ án).

Ghi append-only vào `backend/data/sentiment_history.csv`. Mỗi lần
`compute_coin` hoàn tất sẽ emit 1 dòng / trục điểm (news, macro, social).
Dùng `asyncio.Lock` để tuần tự hoá write giữa các TaskGroup concurrent
(Semaphore 4 trong score_engine).
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_HEADER = ["timestamp", "symbol", "source", "sentiment_label", "sentiment_score"]
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CSV_PATH = _DATA_DIR / "sentiment_history.csv"
_ARCHIVE_PREFIX = "sentiment_history_"
_ARCHIVE_SUFFIX = ".csv"


class SentimentLogger:
    """Singleton-style logger. Dùng qua instance `sentiment_logger` bên dưới."""

    def __init__(self, path: Path = _CSV_PATH, retention_days: int = 30) -> None:
        self._path = path
        self._retention_days = retention_days
        self._lock = asyncio.Lock()
        self._ensured = False
        self._active_day_key: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    def history_paths(self) -> list[Path]:
        """Danh sách file history theo thời gian tăng dần (archive cũ -> file hiện tại)."""
        files: list[tuple[str, Path]] = []
        for p in self._path.parent.glob(f"{_ARCHIVE_PREFIX}*{_ARCHIVE_SUFFIX}"):
            stem = p.stem  # sentiment_history_YYYYMMDD
            day = stem.replace(_ARCHIVE_PREFIX, "", 1)
            if len(day) == 8 and day.isdigit():
                files.append((day, p))
        files.sort(key=lambda x: x[0])
        out = [p for _, p in files]
        if self._path.exists():
            out.append(self._path)
        return out

    def _ensure_file_sync(self) -> None:
        """Tạo data dir + header nếu file chưa tồn tại. Gọi trong lock."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", encoding="utf-8", newline="") as f:
                    csv.writer(f).writerow(_HEADER)
            if self._active_day_key is None:
                mtime = datetime.fromtimestamp(
                    self._path.stat().st_mtime, tz=timezone.utc
                )
                self._active_day_key = mtime.strftime("%Y%m%d")
            self._ensured = True
        except Exception as e:
            log.warning(f"SentimentLogger ensure file lỗi: {e}")

    def _archive_path(self, day_key: str) -> Path:
        return self._path.parent / f"{_ARCHIVE_PREFIX}{day_key}{_ARCHIVE_SUFFIX}"

    def _rotate_if_needed_sync(self, now_utc: datetime) -> None:
        """Rotate theo ngày UTC: file hiện tại -> archive YYYYMMDD, rồi tạo file mới."""
        today_key = now_utc.strftime("%Y%m%d")
        if self._active_day_key is None:
            self._active_day_key = today_key
            return
        if self._active_day_key == today_key:
            return

        if self._path.exists() and self._path.stat().st_size > 0:
            archive = self._archive_path(self._active_day_key)
            if archive.exists():
                # Tránh đè archive cũ nếu service restart nhiều lần trong ngày.
                archive = self._path.parent / (
                    f"{_ARCHIVE_PREFIX}{self._active_day_key}_{int(now_utc.timestamp())}{_ARCHIVE_SUFFIX}"
                )
            self._path.replace(archive)

        with self._path.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(_HEADER)
        self._active_day_key = today_key
        self._cleanup_old_archives_sync(now_utc)

    def _cleanup_old_archives_sync(self, now_utc: datetime) -> None:
        cutoff = (now_utc - timedelta(days=self._retention_days)).strftime("%Y%m%d")
        for p in self._path.parent.glob(f"{_ARCHIVE_PREFIX}*{_ARCHIVE_SUFFIX}"):
            stem = p.stem.replace(_ARCHIVE_PREFIX, "", 1)
            day_key = stem[:8]
            if len(day_key) == 8 and day_key.isdigit() and day_key < cutoff:
                try:
                    p.unlink(missing_ok=True)
                except Exception as e:
                    log.warning(f"xóa archive cũ thất bại ({p.name}): {e}")

    async def log_sentiment(
        self,
        symbol: str,
        source: str,
        label: str | None,
        score: float | None,
    ) -> None:
        """Append 1 dòng vào CSV. Không bao giờ raise (nuốt mọi exception)."""
        if score is None:
            # Trục không có dữ liệu → bỏ qua để CSV gọn.
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with self._lock:
                if not self._ensured:
                    self._ensure_file_sync()
                now_utc = datetime.now(timezone.utc)
                self._rotate_if_needed_sync(now_utc)
                # Build dòng qua csv module để escape đúng chuẩn.
                buf = io.StringIO()
                csv.writer(buf).writerow(
                    [
                        ts,
                        symbol,
                        source,
                        label or "",
                        f"{float(score):.4f}",
                    ]
                )
                line = buf.getvalue()
                # Append nhị phân nhanh, không cần aiofiles cho 1 dòng nhỏ.
                await asyncio.to_thread(self._append_line, line)
        except Exception as e:
            log.warning(f"log_sentiment lỗi ({symbol}/{source}): {e}")

    def _append_line(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8", newline="") as f:
            f.write(line)


sentiment_logger = SentimentLogger()
