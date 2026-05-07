import asyncio
import logging
import math
from datetime import datetime, timezone

from analyzers.sentiment import analyze_texts_async
from clients.binance import fetch_funding_score
from clients.coindesk_news import fetch_coin_news
from clients.reddit import fetch_matched_posts
from clients.telegram import fetch_telegram_news_for_coin
from core.time import format_vn, now_utc
from repositories import coin_repo, news_repo, sentiment_repo
from services.macro_service import get_macro_score

log = logging.getLogger(__name__)

WEIGHTS = {"news": 0.25, "macro": 0.25, "social": 0.25, "sentiment": 0.25}
TIER_RANGES = {1: (0, 10), 2: (10, 30), 3: (30, 50), 4: (50, 100)}

SOURCE_TIMEOUT = 180

MAX_NEWS_FOR_ANALYSIS = 10
MAX_POSTS_FOR_ANALYSIS = 15   # dùng để tính avg sentiment score
MAX_POSTS_TO_SAVE = 100       # số post lưu DB để hiển thị (= social_mentions)
NEWS_LOOKBACK_HOURS = 48


def _fmt_axis(v: float | None, good_thr: float = 6.0, bad_thr: float = 4.0) -> str:
    """Mô tả 1 trục điểm 0–10 bằng tiếng Việt."""
    if v is None:
        return "chưa có dữ liệu"
    if v >= 7.5:
        return "rất tích cực"
    if v >= good_thr:
        return "tích cực"
    if v > bad_thr:
        return "trung tính"
    if v > 2.5:
        return "tiêu cực"
    return "rất tiêu cực"


def build_narrative(
    symbol: str,
    scores: dict,
    label: str,
    social_mentions: int | None = None,
) -> str:
    """Sinh đoạn tóm tắt 3-4 câu cho trang chi tiết coin dựa trên điểm
    các trục — KHÔNG phụ thuộc Gemini quota. Mục tiêu: mỗi snapshot
    luôn có summary hiển thị trên CoinHeader & panel Tin tức."""
    news_v = scores.get("news")
    macro_v = scores.get("macro")
    social_v = scores.get("social")
    sentiment_v = scores.get("sentiment")

    parts: list[str] = []
    parts.append(
        f"Trong 24 giờ qua, tâm lý tổng thể đối với {symbol} được đánh giá ở "
        f"mức {label.lower()}."
    )

    news_desc = _fmt_axis(news_v)
    macro_desc = _fmt_axis(macro_v)
    parts.append(
        f"Dòng tin tức đang {news_desc}, trong khi bối cảnh vĩ mô "
        f"(lạm phát, lãi suất, DXY) đang {macro_desc}."
    )

    if social_v is None or (social_mentions or 0) == 0:
        social_sentence = (
            "Cộng đồng mạng xã hội hầu như chưa thảo luận về coin này trong 24h qua, "
            "tín hiệu xã hội vì vậy còn yếu."
        )
    else:
        social_sentence = (
            f"Mức độ thảo luận {_fmt_axis(social_v, good_thr=6.5, bad_thr=3.5)}"
        )
        if sentiment_v is not None:
            social_sentence += (
                f", tín hiệu funding rate trên Binance đang {_fmt_axis(sentiment_v)}."
            )
        else:
            social_sentence += "."
    parts.append(social_sentence)

    if label in ("Hoàn toàn tích cực", "Tích cực"):
        parts.append(
            "Các yếu tố tích cực đang chiếm ưu thế, tuy nhiên nhà đầu tư cần "
            "theo dõi biến động vĩ mô để chủ động điều chỉnh vị thế."
        )
    elif label in ("Hoàn toàn tiêu cực", "Tiêu cực"):
        parts.append(
            "Áp lực bán vẫn lớn, độ tin cậy của tín hiệu hồi phục còn thấp "
            "cho tới khi có chất xúc tác từ tin tức hoặc dòng tiền."
        )
    elif label == "Bình thường":
        parts.append(
            "Thị trường trong trạng thái cân bằng, nên theo dõi thêm tín hiệu "
            "từ tin tức và khối lượng giao dịch trước khi hành động."
        )
    return " ".join(parts)


def calculate_total(scores: dict) -> float:
    """Tổng 0–10. Bỏ qua các trục `None`, renormalize trọng số trên các
    trục còn lại, sau đó nhân hệ số độ đầy đủ data (coverage penalty) để
    tránh coin ít trục nhưng tích cực lên top hơn coin đủ 4 trục.

    penalty = coverage (tuyến tính, phạt nặng khi thiếu dữ liệu)
      - 4/4 trục → 1.00 (không phạt)
      - 3/4 trục → 0.75
      - 2/4 trục → 0.50
      - 1/4 trục → 0.25
    """
    avail = {k: v for k, v in scores.items() if v is not None and k in WEIGHTS}
    if not avail:
        return 0.0
    w_sum = sum(WEIGHTS[k] for k in avail)
    if w_sum <= 0:
        return 0.0
    raw = sum(avail[k] * WEIGHTS[k] for k in avail) / w_sum
    coverage = len(avail) / len(WEIGHTS)
    # penalty = coverage (tuyến tính): 4/4→1.0, 3/4→0.75, 2/4→0.50, 1/4→0.25
    # Phạt nặng hơn công thức cũ (0.5+0.5*coverage) để tránh coin ít dữ liệu lên top.
    penalty = coverage
    return round(raw * penalty, 2)


def get_label(score: float) -> str:
    if score <= 0:
        return "Không có dữ liệu"
    if score >= 6.5:
        return "Hoàn toàn tích cực"
    if score >= 5.5:
        return "Tích cực"
    if score >= 4.5:
        return "Bình thường"
    if score > 3.0:
        return "Tiêu cực"
    return "Hoàn toàn tiêu cực"


def get_color(label: str) -> str:
    return {
        "Hoàn toàn tích cực": "#16a34a",
        "Tích cực": "#4ade80",
        "Bình thường": "#eab308",
        "Tiêu cực": "#f87171",
        "Hoàn toàn tiêu cực": "#dc2626",
    }.get(label, "#6b7280")


async def _score_news(symbol: str, coin_name: str | None = None) -> float | None:
    """Trả điểm 0–10 (TRUNG BÌNH 24h) hoặc None nếu không có dữ liệu.

    Hai nguồn:
      - CoinDesk API (news_items.source='coindesk')
      - Telegram public channel (news_items.source='telegram')
    Chạy song song, persist vào DB, rồi lấy avg_score từ cả 2.
    """
    # Chạy song song 2 nguồn
    coindesk_task = asyncio.create_task(fetch_coin_news(symbol, coin_name))
    tg_coin_task = asyncio.create_task(fetch_telegram_news_for_coin(symbol))
    articles, tg_articles = await asyncio.gather(
        coindesk_task, tg_coin_task, return_exceptions=True
    )
    if isinstance(articles, BaseException):
        log.warning(f"coindesk news loi ({symbol}): {articles}")
        articles = []
    if isinstance(tg_articles, BaseException):
        log.warning(f"telegram coin news loi ({symbol}): {tg_articles}")
        tg_articles = []

    # --- Ingest CoinDesk ---
    # Dọn bài CoinDesk cũ hơn NEWS_LOOKBACK_HOURS (48h) mỗi cycle.
    # Đảm bảo bài bị insert nhầm do filter cũ sẽ tự mất sau 2 ngày.
    try:
        await news_repo.delete_stale_by_coin_source(symbol, "coindesk", keep_hours=NEWS_LOOKBACK_HOURS)
    except Exception as e:
        log.warning(f"delete_stale coindesk loi ({symbol}): {e}")

    if not articles:
        coindesk_avg = await news_repo.avg_score(
            symbol, "coindesk", hours=NEWS_LOOKBACK_HOURS
        )
    else:
        urls = [a["url"] for a in articles]
        existing = await news_repo.exists_many(urls)
        new_articles = [a for a in articles if a["url"] not in existing]
        if new_articles:
            new_articles.sort(
                key=lambda a: a.get("published_at")
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            new_articles = new_articles[:MAX_NEWS_FOR_ANALYSIS]
            texts = [
                a.get("text_for_analysis") or a["title"] for a in new_articles
            ]
            results = await analyze_texts_async(texts)
            if results:
                await news_repo.bulk_insert(
                    new_articles, results, symbol, "coindesk"
                )
        coindesk_avg = await news_repo.avg_score(
            symbol, "coindesk", hours=NEWS_LOOKBACK_HOURS
        )

    # --- Ingest Telegram coin news (tích lũy như CoinDesk, không xóa+chèn lại) ---
    tg_avg = None
    if tg_articles:
        tg_urls = [p["url"] for p in tg_articles if p.get("url")]
        tg_existing = await news_repo.exists_many(tg_urls) if tg_urls else set()
        tg_new = [p for p in tg_articles if p.get("url") and p["url"] not in tg_existing]
        if tg_new:
            tg_new.sort(
                key=lambda p: p.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            tg_new = tg_new[:MAX_NEWS_FOR_ANALYSIS]
            tg_texts = [p["title"] for p in tg_new if p.get("title")]
            if tg_texts:
                tg_results = await analyze_texts_async(tg_texts)
                if tg_results:
                    await news_repo.bulk_insert(tg_new[: len(tg_results)], tg_results, symbol, "telegram")
        tg_avg = await news_repo.avg_score(symbol, "telegram", hours=NEWS_LOOKBACK_HOURS)

    # --- Kết hợp: nếu cả 2 có dữ liệu → trung bình, ngược lại dùng nguồn còn lại ---
    if coindesk_avg is not None and tg_avg is not None:
        return round((coindesk_avg + tg_avg) / 2, 2)
    return coindesk_avg if coindesk_avg is not None else tg_avg


async def _score_social(symbol: str, relaxed: bool = False) -> tuple[float, int]:
    """Điểm MXH tổng hợp từ nguồn: Reddit.

    Trả `(score 0–10, total_mention_count)`.
    relaxed=True (tier 1/2): bao gồm tin crypto chung, loại bài về coin khác.
    relaxed=False (tier 3/4): chỉ bài nhắc đến coin này.
    """
    reddit_task = asyncio.create_task(fetch_matched_posts(symbol, relaxed=relaxed))

    reddit_posts = await reddit_task

    if isinstance(reddit_posts, BaseException):
        log.warning(f"reddit loi ({symbol}): {reddit_posts}")
        reddit_posts = []

    try:
        await news_repo.delete_recent_by_coin_source(symbol, "reddit", 24)
    except Exception as e:
        log.warning(f"clear social feed loi ({symbol}): {e}")

    total_count = len(reddit_posts)
    if total_count == 0:
        return 3.0, 0  # phạt: không có thảo luận = tín hiệu cộng đồng yếu

    # Posts để lưu DB (hiển thị) — mới nhất trước, giới hạn MAX_POSTS_TO_SAVE.
    posts_to_save = sorted(
        reddit_posts, key=lambda p: p.get("published_at"), reverse=True
    )[:MAX_POSTS_TO_SAVE]

    reddit_avg_score = 5.0  # fallback neutral nếu model lỗi
    saved_count = 0
    try:
        new_posts = [p for p in posts_to_save if p.get("url")]
        if new_posts:
            titles = [p.get("title", "") for p in new_posts]
            new_analyses = await analyze_texts_async(titles)
            await news_repo.bulk_insert(
                new_posts[: len(new_analyses)], new_analyses, symbol, "reddit"
            )
            saved_count = len(new_posts[: len(new_analyses)])
            if new_analyses:
                reddit_avg_score = sum(
                    r.get("score", 5.0) for r in new_analyses
                ) / len(new_analyses)
    except Exception as e:
        log.warning(f"reddit sentiment loi ({symbol}): {e}")

    # --- Kết hợp điểm ---
    # Volume score dùng total_count (toàn bộ match, kể cả > MAX_POSTS_TO_SAVE).
    volume_score = (
        min(10.0, 10.0 * (math.log1p(total_count) / math.log1p(100)))
        if total_count > 0
        else 0.0
    )

    # 40% volume + 60% sentiment thực
    final_score = 0.4 * volume_score + 0.6 * reddit_avg_score

    log.info(
        f"Social {symbol}: total={total_count} saved={saved_count} "
        f"vol={volume_score:.2f} sentiment={reddit_avg_score:.2f} final={final_score:.2f}"
    )
    # Trả saved_count để social_mentions khớp với số bài hiển thị trên UI.
    return round(min(10.0, final_score), 2), saved_count


async def _safe(label: str, symbol: str, coro):
    """Chạy coroutine với timeout + nuốt exception. Trả None nếu lỗi/hết giờ.
    ĐẢM BẢO compute_coin không hang + không raise (quy tắc 10, 13)."""
    try:
        return await asyncio.wait_for(coro, timeout=SOURCE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning(f"{label} timeout ({symbol}) sau {SOURCE_TIMEOUT}s")
    except Exception as e:
        log.warning(f"{label} loi ({symbol}): {e}")
    return None


async def compute_coin(
    coin_id: str, symbol: str, coin_name: str | None = None,
    coin_rank: int | None = None,
) -> dict:
    """Pipeline đầy đủ cho 1 coin. Mỗi trục độc lập:
    - Có dữ liệu → số 0–10
    - Không có dữ liệu → None (không tính vào total)
    Mỗi nguồn có timeout riêng nên tier1/2/3 không bao giờ hang.

    coin_rank ≤ 30 (tier 1/2): dùng relaxed Reddit matching.
    """
    relaxed = coin_rank is not None and coin_rank <= 30

    scores: dict[str, float | None] = {
        "news": None,
        "macro": None,
        "social": None,
        "sentiment": None,
    }

    scores["news"] = await _safe(
        "score_news", symbol, _score_news(symbol, coin_name)
    )

    try:
        from services.macro_service import _macro_cache

        if _macro_cache.get("updated_at"):
            scores["macro"] = float(get_macro_score())
    except Exception as e:
        log.warning(f"score_macro loi ({symbol}): {e}")

    social_result = await _safe(
        "score_social", symbol, _score_social(symbol, relaxed=relaxed)
    )
    social_mentions: int | None = None
    if social_result is not None:
        scores["social"], social_mentions = social_result
    scores["sentiment"] = await _safe(
        "score_sentiment", symbol, fetch_funding_score(symbol)
    )

    total = calculate_total(scores)
    label = get_label(total)

    summary: str | None = None
    if total > 0 and label != "Không có dữ liệu":
        summary = build_narrative(symbol, scores, label, social_mentions)

    try:
        await sentiment_repo.insert_snapshot(
            coin_id, scores, total, label, summary, now_utc(),
            social_mentions=social_mentions,
        )
    except Exception as e:
        log.warning(f"insert_snapshot loi ({symbol}): {e}")

    def _fmt(v):
        return "—" if v is None else f"{v:.2f}"

    log.info(
        f"[{format_vn(now_utc())}] {symbol}: total={total:.1f} {label} "
        f"| news={_fmt(scores['news'])} macro={_fmt(scores['macro'])} "
        f"social={_fmt(scores['social'])}({social_mentions}) "
        f"sentiment={_fmt(scores['sentiment'])}"
    )
    return {
        "score_total": total,
        "label": label,
        "social_mentions": social_mentions,
        **scores,
    }


async def compute_tier(tier: int) -> None:
    """Được APScheduler gọi. Tính sentiment cho coin của tier với
    concurrency = 4 — BẮT BUỘC TaskGroup (Py 3.12+) + Semaphore(4)
    dạng `async with sem:` (quy tắc 13)."""
    try:
        coins = await coin_repo.get_sorted_by_rank()
    except Exception as e:
        log.exception(f"compute_tier get_sorted_by_rank loi: {e}")
        return

    start, end = TIER_RANGES.get(tier, (0, 0))
    tier_coins = coins[start:end]
    log.info(
        f"[{format_vn(now_utc())}] Tier {tier}: {len(tier_coins)} coin"
    )
    if not tier_coins:
        return

    sem = asyncio.Semaphore(4)

    async def _one(coin) -> None:
        async with sem:
            try:
                await compute_coin(coin.id, coin.symbol, coin.name, coin_rank=coin.rank)
            except Exception as e:
                log.exception(
                    f"compute_coin {coin.symbol} loi ngoai du kien: {e}"
                )

    async with asyncio.TaskGroup() as tg:
        for c in tier_coins:
            tg.create_task(_one(c))
