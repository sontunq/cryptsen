
from __future__ import annotations

import logging

import anyio

from core.config import settings
from core.time import now_utc, format_vn

log = logging.getLogger(__name__)

_pipe = None
_MODEL_ID = settings.sentiment_model
_MAX_CONCURRENT = max(1, int(settings.sentiment_max_concurrent_inference))
_inference_limiter = anyio.CapacityLimiter(total_tokens=_MAX_CONCURRENT)


def load_sentiment():
    """Load sentiment model 1 lần trong FastAPI lifespan."""
    global _pipe
    if _pipe is not None:
        return _pipe

    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    _pipe = pipeline(
        "text-classification",
        model=_MODEL_ID,
        tokenizer=_MODEL_ID,
        device=device,
        truncation=True,
        max_length=256,
        top_k=None,
    )

    log.info(
        f"[{format_vn(now_utc())}] Sentiment model loaded "
        f"(model={_MODEL_ID}, device={'GPU' if device == 0 else 'CPU'}, "
        f"max_concurrent={_MAX_CONCURRENT})"
    )
    return _pipe


def get_pipe():
    if _pipe is None:
        raise RuntimeError("Sentiment chưa load — gọi load_sentiment() trước")
    return _pipe


def _norm_label(raw: str) -> str:
    """Chuẩn hoá mọi biến thể nhãn → positive/neutral/negative."""
    s = raw.strip().lower()
    if s in ("positive", "bullish", "label_2"):
        return "positive"
    if s in ("negative", "bearish", "label_0"):
        return "negative"
    return "neutral"


def _score(label: str, confidence: float) -> float:
    """Map → thang 0–10."""
    if confidence < 0.5:
        return 5.0
    if label == "positive":
        return round(5.0 + confidence * 5.0, 2)
    if label == "negative":
        return round(5.0 - confidence * 5.0, 2)
    return 5.0


def _to_probs(item) -> dict[str, float]:
    """Chuẩn hoá output top_k=None thành xác suất theo positive/neutral/negative."""
    probs = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    labels = item if isinstance(item, list) else [item]
    for p in labels:
        lbl = _norm_label(str(p.get("label", "neutral")))
        probs[lbl] = float(p.get("score", 0.0))
    total = sum(probs.values())
    if total > 0:
        return {k: v / total for k, v in probs.items()}
    return {"positive": 0.0, "neutral": 1.0, "negative": 0.0}


def _pick_label_and_confidence(probs: dict[str, float]) -> tuple[str, float]:
    lbl = max(probs, key=probs.get)
    return lbl, float(probs[lbl])


def _run_sync(texts: list[str]) -> list[dict]:
    if not texts:
        return []
    if _pipe is None:
        return [{"score": 5.0, "label": "neutral"} for _ in texts]

    raw = _pipe(texts, batch_size=16)

    out = []
    for item in raw:
        probs = _to_probs(item)

        lbl, confidence = _pick_label_and_confidence(probs)
        out.append({"score": _score(lbl, confidence), "label": lbl})
    return out


async def analyze_texts_async(texts: list[str]) -> list[dict]:
    """Batch inference — CHẠY TRONG THREADPOOL để không block event loop.

    Input:  ["Fed raises rates...", "Bitcoin crashes..."]
    Output: [{"score": 7.2, "label": "positive"}, ...]
    """
    if not texts:
        return []
    try:
        return await anyio.to_thread.run_sync(
            _run_sync,
            texts,
            limiter=_inference_limiter,
        )
    except Exception as e:
        log.warning(f"Sentiment lỗi: {e}")
        return [{"score": 5.0, "label": "neutral"} for _ in texts]
