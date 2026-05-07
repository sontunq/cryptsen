import json
import logging
import re

import google.generativeai as genai
from aiolimiter import AsyncLimiter

from core.breaker import CircuitBreaker
from core.config import settings
from core.time import format_vn, now_utc

log = logging.getLogger(__name__)

# Configure model — JSON mode buộc Gemini trả JSON thuần (quy tắc 11).
genai.configure(api_key=settings.gemini_api_key)
_model = genai.GenerativeModel(
    settings.gemini_model,  # mặc định gemini-1.5-flash (free 1,500/ngày, 15 RPM)
    generation_config={"response_mime_type": "application/json"},
)

# gemini-2.5-flash free tier = 10 RPM. Scheduler dùng tối đa 7 RPM,
# chừa 3 RPM cho chat endpoint.
_rate_limit = AsyncLimiter(max_rate=7, time_period=60)
_breaker = CircuitBreaker(threshold=5, cooldown=600)

# Gemini đôi khi vẫn quấn JSON trong ```json ... ``` dù đã set mime type.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fence(text: str) -> str:
    """Bóc fence markdown trước khi json.loads."""
    return _FENCE_RE.sub("", text).strip()


async def _call(prompt: str) -> str | None:
    """Wrapper đồng nhất: rate limit + circuit breaker.
    Trả None nếu breaker OPEN hoặc request lỗi."""
    if not _breaker.allow():
        log.warning(
            f"[{format_vn(now_utc())}] Gemini circuit OPEN — skip call"
        )
        return None
    async with _rate_limit:  # ✅ token bucket: strict 14 RPM
        try:
            resp = await _model.generate_content_async(prompt)
            _breaker.record(True)
            return resp.text
        except Exception as e:
            _breaker.record(False)
            log.warning(f"[{format_vn(now_utc())}] Gemini lỗi: {e}")
            return None


# ------------------- Prompts -------------------

BATCH_PROMPT = """Bạn là chuyên gia phân tích tâm lý cộng đồng crypto.
Phân tích sentiment của {n} tiêu đề bài đăng Reddit sau, liên quan đến {coin}.

{numbered_texts}

Trả về JSON array ĐÚNG format (không markdown, không backtick):
[{{"score": <0.0-10.0>, "label": "<positive|neutral|negative>", "reason": "<1 câu tiếng Việt>"}}, ...]

Thang điểm: 8-10=rất tích cực | 6-7=tích cực | 4-5=trung tính | 2-3=tiêu cực | 0-1=rất tiêu cực
Hiểu tiếng lóng: fomo, rekt, ngmi, wagmi, wen moon, hodl, dump, pump, to the moon, rug pull..."""


async def analyze_reddit_batch(
    posts: list[str], coin_symbol: str
) -> list[dict]:
    """Gửi 1 request Gemini cho toàn bộ posts của 1 coin (batch).
    Fallback neutral 5.0 nếu lỗi hoặc response không parse được."""
    if not posts:
        return []
    numbered = "\n".join(f"{i+1}. {t[:200]}" for i, t in enumerate(posts))
    raw = await _call(
        BATCH_PROMPT.format(
            n=len(posts), coin=coin_symbol, numbered_texts=numbered
        )
    )
    fallback = [
        {"score": 5.0, "label": "neutral", "reason": None} for _ in posts
    ]
    if raw is None:
        return fallback
    try:
        results = json.loads(_strip_fence(raw))
        if not isinstance(results, list) or len(results) != len(posts):
            raise ValueError("Số kết quả Gemini không khớp với posts")
        return results
    except Exception as e:
        log.warning(f"Gemini Reddit parse lỗi ({coin_symbol}): {e}")
        return fallback


async def generate_reason(
    title: str, label: str, coin: str
) -> str | None:
    """Sinh lý do ngắn cho 1 bài tin nổi bật. CHỈ gọi cho top bài cực
    đoan (score ≥ 8 hoặc ≤ 2) — tối đa 3 bài/cycle/coin."""
    prompt = (
        f'Trả về JSON {{"reason": "<1 câu tiếng Việt>"}} giải thích tại sao '
        f'tiêu đề "{title[:300]}" là {label} với {coin}.'
    )
    raw = await _call(prompt)
    if raw is None:
        return None
    try:
        return json.loads(_strip_fence(raw)).get("reason")
    except Exception:
        return None


async def generate_coin_summary(
    symbol: str, scores: dict, label: str
) -> str:
    """Sinh đoạn tóm tắt cho trang chi tiết coin. CHỈ gọi khi `label`
    đổi so với lần trước (quy tắc 11 — tiết kiệm quota)."""
    def _s(v):
        return "—" if v is None else f"{v:.1f}/10"

    prompt = (
        f'Trả về JSON {{"summary": "<2-3 câu tiếng Việt>"}}:\n'
        f"Viết tóm tắt tâm lý thị trường cho {symbol}.\n"
        f"Dữ liệu: Tin tức={_s(scores.get('news'))}, "
        f"Vĩ mô={_s(scores.get('macro'))}, "
        f"Mạng XH={_s(scores.get('social'))}, "
        f"Funding={_s(scores.get('funding'))}. Nhãn: {label}.\n"
        f'KHÔNG dùng cụm "lời khuyên đầu tư".'
    )
    raw = await _call(prompt)
    if raw is None:
        return f"{symbol} đang ở trạng thái {label}."
    try:
        parsed = json.loads(_strip_fence(raw))
        return parsed.get("summary") or f"{symbol} đang ở trạng thái {label}."
    except Exception:
        return f"{symbol} đang ở trạng thái {label}."
