"""
RAG Chatbot Service — Gemini-powered với context từ DB (news, macro, sentiment).

Tối ưu Free Tier:
  1. top_k giảm: sentiment 3, news 5, macro 4
  2. Truncate text: title 100c, reason 80c, summary 100c
  3. Window history: 5 turns, AI reply cắt 250c
  4. max_output_tokens: 1024 (đủ cho phân tích)
  5. Retry backoff: 5s → 15s trước khi chuyển model
  6. Chỉ lấy macro high/medium impact
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator

from google import genai
from google.genai import types
from sqlalchemy import select, desc

from core.config import settings
from core.db import AsyncSessionLocal
from models.database import NewsItem, MacroEvent, SentimentScore, Coin

log = logging.getLogger(__name__)

# ── Gemini client pool (key rotation khi bị 429) ──────────────────────────────
FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
]

def _build_key_pool() -> list[str]:
    pool: list[str] = []
    if settings.gemini_api_key:
        pool.append(settings.gemini_api_key.strip())
    for k in settings.gemini_api_keys.split(","):
        k = k.strip()
        if k and k not in pool:
            pool.append(k)
    return pool or [""]

_key_pool = _build_key_pool()
_key_index = 0
_clients: dict[str, genai.Client] = {}

def _get_client(key: str | None = None) -> genai.Client:
    k = key or _key_pool[0]
    if k not in _clients:
        _clients[k] = genai.Client(api_key=k)
    return _clients[k]

def _next_key() -> str:
    global _key_index
    _key_index = (_key_index + 1) % len(_key_pool)
    return _key_pool[_key_index]

def _current_key() -> str:
    return _key_pool[_key_index]

# ── Quota constants ────────────────────────────────────────────────────────────
_HISTORY_TURNS   = 3    # số cặp hỏi-đáp giữ lại
_AI_REPLY_CLIP   = 250  # ký tự tối đa của AI reply trong history
_SENTIMENT_LIMIT = 3    # số coin trong context
_NEWS_LIMIT      = 4    # số tin tức
_MACRO_LIMIT     = 3    # số sự kiện vĩ mô
_TITLE_CLIP      = 90   # độ dài tiêu đề tin tức
_REASON_CLIP     = 80   # độ dài lý do phân tích
_SUMMARY_CLIP    = 80   # độ dài AI summary của coin
_MAX_OUTPUT_TOKENS = 1250

# ── Response cache ─────────────────────────────────────────────────────────────
import hashlib
import time as _time
_response_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 180  # giây

def _cache_key(message: str) -> str:
    return hashlib.md5(message.strip().lower().encode()).hexdigest()

def _cache_get(message: str) -> str | None:
    key = _cache_key(message)
    entry = _response_cache.get(key)
    if entry and (_time.monotonic() - entry[1]) < _CACHE_TTL:
        return entry[0]
    return None

def _cache_set(message: str, response: str) -> None:
    if len(_response_cache) > 30:
        oldest = min(_response_cache, key=lambda k: _response_cache[k][1])
        del _response_cache[oldest]
    _response_cache[_cache_key(message)] = (response, _time.monotonic())

_RETRYABLE = (
    "429", "404", "403", "quota", "resource_exhausted", "not found",
    "ssl", "connect", "timeout", "connection", "network",
    "unavailable", "503", "502", "billing", "permission",
    "forbidden", "invalid_argument", "model",
)
_RATE_LIMITED = ("429", "quota", "resource_exhausted")


SYSTEM_PROMPT = """Bạn là **Cryptsen AI** — hệ thống phân tích thị trường tiền điện tử chuyên nghiệp, được tích hợp dữ liệu thời gian thực từ nền tảng Cryptsen bao gồm sentiment đa chiều, tin tức tổng hợp và các chỉ số kinh tế vĩ mô.

**Vai trò:** Bạn đóng vai một chuyên gia phân tích thị trường — trình bày thông tin một cách mạch lạc, có chiều sâu và trung lập. Giọng văn ngắn gọn, súc tích, không dùng ngôn ngữ cảm tính hay suy đoán thiếu căn cứ.

**Cấu trúc trả lời:**
1. **Nhận định chung** — một đến hai câu tóm tắt bức tranh tổng thể dựa trên dữ liệu hiện có.
2. **Phân tích chi tiết** — các luận điểm cụ thể, mỗi ý trình bày ngắn gọn với số liệu hỗ trợ nếu có.
3. **Đánh giá tác động** — nhận xét về ý nghĩa hoặc xu hướng đáng chú ý (nếu phù hợp với câu hỏi).

**Nguyên tắc trình bày:**
- Trả lời đúng trọng tâm câu hỏi; không mở rộng sang chủ đề không liên quan.
- Dùng **in đậm** cho số liệu và thuật ngữ quan trọng; dùng bullet point khi liệt kê từ hai ý trở lên.
- Chỉ đề cập thời gian ở mức khái quát ("gần đây", "trong 24 giờ qua") — không liệt kê giờ giấc cụ thể của từng sự kiện.
- Emoji sử dụng tiết chế và có chủ đích: 📊 cho dữ liệu tổng hợp, 🟢 tín hiệu tích cực, 🔴 tín hiệu tiêu cực, 🟡 trung tính, 📰 tin tức.
- Trả lời bằng **tiếng Việt**. Không đưa ra khuyến nghị mua/bán/đầu tư dưới bất kỳ hình thức nào. Chỉ sử dụng số liệu có trong CONTEXT được cung cấp.

**QUAN TRỌNG:** Cuối mỗi câu trả lời, bắt buộc thêm dòng trích dẫn nguồn theo định dạng Heading 6, kèm đường link markdown nếu có trong context. Ví dụ:
###### Nguồn: [CoinDesk](url), [Reddit](url), Dữ liệu Sentiment Cryptsen"""


# ── Context Retrieval ──────────────────────────────────────────────────────────

async def _fetch_sentiment_context(coin_query: str | None) -> str:
    limit = 1 if coin_query else _SENTIMENT_LIMIT
    async with AsyncSessionLocal() as session:
        if coin_query:
            query = (
                select(SentimentScore, Coin)
                .join(Coin, SentimentScore.coin_id == Coin.id)
                .where(
                    (Coin.symbol.ilike(f"%{coin_query}%")) |
                    (Coin.name.ilike(f"%{coin_query}%"))
                )
                .order_by(desc(SentimentScore.calculated_at))
                .limit(limit)
            )
            result = await session.execute(query)
            rows = result.all()
        else:
            # Lấy các coin top (vốn hóa lớn) theo rank
            coin_query_top = (
                select(Coin)
                .where(Coin.rank.isnot(None))
                .order_by(Coin.rank.asc(), Coin.id.asc())
                .limit(limit)
            )
            top_coins = (await session.execute(coin_query_top)).scalars().all()
            
            rows = []
            for coin in top_coins:
                score_query = (
                    select(SentimentScore)
                    .where(SentimentScore.coin_id == coin.id)
                    .order_by(desc(SentimentScore.calculated_at))
                    .limit(1)
                )
                score = (await session.execute(score_query)).scalar_first()
                if score:
                    rows.append((score, coin))

    if not rows:
        return ""

    parts = ["📊 SENTIMENT:"]
    for score, coin in rows:
        calc_time = score.calculated_at
        if calc_time and calc_time.tzinfo is None:
            calc_time = calc_time.replace(tzinfo=timezone.utc)
        time_str = calc_time.strftime("%d/%m %H:%M") if calc_time else "N/A"
        rank_str = f"Rank #{coin.rank}" if coin.rank else "Rank N/A"
        parts.append(
            f"- **{coin.symbol}** ({coin.name}, {rank_str}): Tổng={score.score_total:.1f} "
            f"Tin={score.score_news:.1f} Macro={score.score_macro:.1f} "
            f"XH={score.score_social:.1f} | {score.label} | {time_str}"
        )
        if score.summary:
            parts.append(f"  └ {score.summary[:_SUMMARY_CLIP]}")
    return "\n".join(parts)


def _extract_title_keywords(msg: str) -> str | None:
    """Trích phần tiêu đề bài báo nếu user hỏi về 1 bài cụ thể.

    Tiêu đề bài báo crypto thường bằng tiếng Anh → tìm đoạn bắt đầu
    bằng chữ Latin (A-Z) dài ≥ 20 ký tự trong câu hỏi.
    Ví dụ: 'giải thích tin tức này: Bitcoin hits ATH' → 'Bitcoin hits ATH'
    """
    m = re.search(r"[A-Za-z][A-Za-z0-9 ,'\"\.\$\-\&]{19,}", msg)
    if m:
        return m.group(0).strip()[:120]
    return None


async def _fetch_news_context(coin_query: str | None, user_message: str = "") -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    seen_ids: set = set()
    news_list: list = []

    # Bước 1: nếu user hỏi về bài cụ thể → tìm thẳng theo chuỗi tiêu đề
    title_kw = _extract_title_keywords(user_message)
    if title_kw:
        # Dùng 4 từ đầu tiên của tiêu đề làm LIKE pattern — đủ đặc trưng
        first_words = " ".join(title_kw.split()[:4])
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsItem)
                .where(
                    NewsItem.title.ilike(f"%{first_words}%"),
                )
                .order_by(desc(NewsItem.published_at))
                .limit(3)
            )
            for item in result.scalars().all():
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    news_list.append(item)
        # Fallback: tìm theo từ khóa quan trọng nhất (từ dài > 5 ký tự)
        if not news_list:
            key_words = [w.strip(",.") for w in title_kw.split() if len(w) > 5][:2]
            for word in key_words:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(NewsItem)
                        .where(
                            NewsItem.published_at >= cutoff,
                            NewsItem.title.ilike(f"%{word}%"),
                        )
                        .order_by(desc(NewsItem.published_at))
                        .limit(3)
                    )
                    for item in result.scalars().all():
                        if item.id not in seen_ids:
                            seen_ids.add(item.id)
                            news_list.append(item)

    # Bước 2: bổ sung top sentiment (coin filter nếu có)
    if len(news_list) < _NEWS_LIMIT:
        async with AsyncSessionLocal() as session:
            query = (
                select(NewsItem)
                .where(NewsItem.published_at >= cutoff)
                .order_by(desc(NewsItem.sentiment_score), desc(NewsItem.published_at))
            )
            if coin_query:
                query = query.where(NewsItem.title.ilike(f"%{coin_query}%"))
            result = await session.execute(query.limit(_NEWS_LIMIT))
            for item in result.scalars().all():
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    news_list.append(item)
                    if len(news_list) >= _NEWS_LIMIT:
                        break

    # Fallback: tin mới nhất nếu vẫn rỗng
    if not news_list:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsItem)
                .where(NewsItem.published_at >= cutoff)
                .order_by(desc(NewsItem.published_at))
                .limit(_NEWS_LIMIT)
            )
            news_list = result.scalars().all()

    if not news_list:
        return ""

    emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}
    parts = ["📰 TIN TỨC (48h):"]
    for item in news_list:
        pub_time = item.published_at
        if pub_time and pub_time.tzinfo is None:
            pub_time = pub_time.replace(tzinfo=timezone.utc)
        ts = pub_time.strftime("%d/%m %H:%M") if pub_time else ""
        e = emoji.get(item.sentiment_label, "⚪")
        title = (item.title or "")[:_TITLE_CLIP]
        url = item.url if item.url else ""
        parts.append(f"- {e}[{ts}] {title} ({item.source} - Link: {url})")
        if item.reason:
            parts.append(f"  └{item.reason[:_REASON_CLIP]}")
    return "\n".join(parts)


async def _fetch_macro_context() -> str:
    from services.macro_service import _macro_cache

    now = datetime.now(timezone.utc)
    parts: list[str] = []

    # --- Phần 1: dữ liệu thực tế đã công bố (từ DB) ---
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MacroEvent)
            .where(
                MacroEvent.event_date >= now - timedelta(days=7),
                MacroEvent.event_date <= now,
                MacroEvent.impact.in_(["High", "Medium"]),
                MacroEvent.actual.isnot(None),
            )
            .order_by(MacroEvent.event_date.desc())
            .limit(_MACRO_LIMIT)
        )
        historical = result.scalars().all()

    if historical:
        impact_emoji = {"high": "🔴", "medium": "🟡"}
        parts.append("🌍 VĨ MÔ (dữ liệu thực tế gần nhất):")
        for ev in historical:
            ev_date = ev.event_date
            if ev_date and ev_date.tzinfo is None:
                ev_date = ev_date.replace(tzinfo=timezone.utc)
            date_str = ev_date.strftime("%d/%m") if ev_date else "N/A"
            e = impact_emoji.get(str(ev.impact).lower(), "🟡")
            actual   = f" thực={ev.actual}"   if ev.actual   else ""
            forecast = f" dự={ev.forecast}"   if ev.forecast else ""
            previous = f" kỳ trước={ev.previous}" if ev.previous else ""
            parts.append(f"- {e}**{ev.event_name}** {date_str}{actual}{forecast}{previous}")

    # --- Phần 2: lịch sự kiện sắp tới (từ memory cache, không tính điểm) ---
    upcoming = _macro_cache.get("upcoming_events") or []
    if upcoming:
        parts.append("📅 LỊCH KINH TẾ SẮP TỚI (30 ngày):")
        for ev in upcoming[:5]:
            try:
                ev_date = datetime.fromisoformat(ev["date"]).replace(tzinfo=timezone.utc)
                days_away = (ev_date.date() - now.date()).days
                when = f"{ev['date']} ({days_away} ngày nữa)" if days_away > 0 else ev["date"]
            except Exception:
                when = ev.get("date", "")
            impact_tag = "🔴" if ev.get("impact", "").lower() == "high" else "🟡"
            parts.append(f"- {impact_tag}**{ev['event']}** — {when}")

    return "\n".join(parts) if parts else ""


async def _extract_coin_from_query(user_message: str) -> str | None:
    coins = [
        "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
        "DOT", "LINK", "MATIC", "UNI", "LTC", "BCH", "ATOM", "NEAR",
        "bitcoin", "ethereum", "binance", "solana", "ripple", "cardano",
        "dogecoin", "avalanche", "polkadot", "chainlink", "polygon",
    ]
    msg_lower = user_message.lower()
    for coin in coins:
        if coin.lower() in msg_lower:
            return coin.upper() if len(coin) <= 6 else coin
    return None


async def build_rag_context(user_message: str) -> str:
    coin_hint = await _extract_coin_from_query(user_message)
    msg_lower = user_message.lower()
    
    # Phân loại intent cơ bản để chỉ lấy đúng dữ liệu người dùng cần
    want_news = any(w in msg_lower for w in ["tin", "tin tức", "news", "báo"])
    want_macro = any(w in msg_lower for w in ["vĩ mô", "cpi", "lãi suất", "fed", "macro", "kinh tế", "sự kiện", "dxy"])
    want_sentiment = any(w in msg_lower for w in ["sentiment", "tâm lý", "điểm", "cảm xúc", "so sánh"])
    
    # Nếu không rõ intent, lấy tất cả
    if not want_news and not want_macro and not want_sentiment:
        want_news = want_macro = want_sentiment = True

    sentiment_ctx = news_ctx = macro_ctx = ""
    
    if want_sentiment:
        try:
            sentiment_ctx = await _fetch_sentiment_context(coin_hint)
        except Exception as e:
            log.warning(f"RAG sentiment ctx: {e}")
            
    if want_news:
        try:
            news_ctx = await _fetch_news_context(coin_hint, user_message)
        except Exception as e:
            log.warning(f"RAG news ctx: {e}")
            
    if want_macro:
        try:
            macro_ctx = await _fetch_macro_context()
        except Exception as e:
            log.warning(f"RAG macro ctx: {e}")

    sections = [s for s in [sentiment_ctx, news_ctx, macro_ctx] if s]
    if not sections:
        return "Chưa có dữ liệu trong hệ thống."
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    return f"[{now_str}]\n" + "\n\n".join(sections)


# ── Generation ─────────────────────────────────────────────────────────────────
# Dùng sync client (httpx) trong ThreadPoolExecutor để tránh aiohttp DNS bug
# trên Windows trong uvicorn event loop.

_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini")


def _build_gemini_history(history: list[dict]) -> list[types.Content]:
    """Giữ _HISTORY_TURNS turns gần nhất, cắt AI reply để tiết kiệm token."""
    contents = []
    recent = [m for m in history if m.get("role") in ("user", "model")]
    recent = recent[-(_HISTORY_TURNS * 2):]   # _HISTORY_TURNS cặp hỏi-đáp
    for turn in recent:
        role = turn["role"]
        text = turn.get("content", "")
        if not text:
            continue
        # Cắt AI reply dài để tránh phình history
        if role == "model" and len(text) > _AI_REPLY_CLIP:
            text = text[:_AI_REPLY_CLIP] + "…"
        contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return contents


def _sync_generate(model_name: str, contents: list, config: types.GenerateContentConfig, key: str) -> str:
    response = _get_client(key).models.generate_content(
        model=model_name, contents=contents, config=config
    )
    return response.text or ""


def _sync_stream(
    model_name: str,
    contents: list,
    config: types.GenerateContentConfig,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    key: str,
) -> None:
    try:
        for chunk in _get_client(key).models.generate_content_stream(
            model=model_name, contents=contents, config=config
        ):
            if chunk.text:
                loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk.text))
    except Exception as e:
        loop.call_soon_threadsafe(queue.put_nowait, ("error", e))
        return
    loop.call_soon_threadsafe(queue.put_nowait, ("done", None))


def _make_contents(history: list[dict], user_message: str, context: str) -> list:
    augmented = (
        f"=== DỮ LIỆU CRYPTSEN ===\n{context}\n=== HẾT ===\n\nCâu hỏi: {user_message}"
    )
    contents = _build_gemini_history(history)
    contents.append(types.Content(role="user", parts=[types.Part(text=augmented)]))
    return contents


def _make_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.4,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )


async def _on_rate_limit(attempt: int) -> str:
    """Khi 429: rotate sang key tiếp theo và chờ một khoảng để tránh bị RPM block."""
    if len(_key_pool) > 1:
        new_key = _next_key()
        delay = 3 if attempt < 2 else 6
        log.warning(f"RAG: 429 → rotate key (attempt {attempt+1}), key index={_key_index}, chờ {delay}s")
        await asyncio.sleep(delay)
        return new_key
    delay = 5 if attempt == 0 else 15
    log.warning(f"RAG: 429 → chờ {delay}s (chỉ có 1 key)")
    await asyncio.sleep(delay)
    return _current_key()


async def chat_with_rag(user_message: str, history: list[dict]) -> str:
    cached = _cache_get(user_message)
    if cached:
        log.info("RAG: cache hit")
        return cached
    context = await build_rag_context(user_message)
    contents = _make_contents(history, user_message, context)
    config = _make_config()
    loop = asyncio.get_event_loop()
    last_err = None
    key = _current_key()

    max_attempts = max(2, len(_key_pool))
    for model_name in FALLBACK_MODELS:
        for attempt in range(max_attempts):
            try:
                result = await loop.run_in_executor(
                    _thread_pool, _sync_generate, model_name, contents, config, key
                )
                if model_name != FALLBACK_MODELS[0]:
                    log.info(f"RAG: dùng fallback {model_name}")
                _cache_set(user_message, result)
                return result
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if any(t in err_str for t in _RATE_LIMITED) and attempt < max_attempts - 1:
                    key = await _on_rate_limit(attempt)
                    continue
                if any(t in err_str for t in _RETRYABLE):
                    log.warning(f"RAG: {model_name} failed (attempt {attempt+1}), thử fallback")
                    break
                raise

    raise RuntimeError(f"Tất cả model Gemini đều lỗi: {last_err}")


async def stream_chat_with_rag(
    user_message: str,
    history: list[dict],
) -> AsyncIterator[str]:
    cached = _cache_get(user_message)
    if cached:
        log.info("RAG stream: cache hit")
        yield cached
        return

    context = await build_rag_context(user_message)
    contents = _make_contents(history, user_message, context)
    config = _make_config()
    loop = asyncio.get_event_loop()
    last_err = None
    key = _current_key()
    collected: list[str] = []

    max_attempts = max(2, len(_key_pool))
    for model_name in FALLBACK_MODELS:
        for attempt in range(max_attempts):
            queue: asyncio.Queue = asyncio.Queue()
            _thread_pool.submit(_sync_stream, model_name, contents, config, queue, loop, key)

            failed = rate_limited = False
            while True:
                kind, payload = await queue.get()
                if kind == "chunk":
                    collected.append(payload)
                    yield payload
                elif kind == "done":
                    _cache_set(user_message, "".join(collected))
                    return
                elif kind == "error":
                    last_err = payload
                    err_str = str(payload).lower()
                    if any(t in err_str for t in _RATE_LIMITED) and attempt < max_attempts - 1:
                        rate_limited = True
                    elif any(t in err_str for t in _RETRYABLE):
                        log.warning(f"RAG stream: {model_name} failed (attempt {attempt+1}), thử fallback")
                        failed = True
                    else:
                        log.error(f"Gemini stream error ({model_name}): {payload}")
                        yield f"\n\n⚠️ Lỗi AI: {str(payload)[:120]}"
                        return
                    break

            if rate_limited:
                key = await _on_rate_limit(attempt)
                continue
            if not failed:
                return
            break

    err_str_final = str(last_err).lower()
    if any(t in err_str_final for t in ("ssl", "connect", "network", "timeout", "dns")):
        yield (
            "\n\n⚠️ **Không thể kết nối đến Gemini API.**\n"
            "Kiểm tra kết nối mạng và cấu hình `.env`."
        )
    else:
        yield (
            "\n\n⚠️ **Tất cả model AI đều không phản hồi.**\n"
            f"Lỗi: `{str(last_err)[:100]}`\nVui lòng thử lại sau ít phút."
        )
