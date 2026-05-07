"""Standalone script đánh giá sentiment model trên tập `eval_crypto_news.csv`.

Chạy từ thư mục `backend/`:

    python -m evaluation.evaluate_sentiment
    # hoặc
    python evaluation/evaluate_sentiment.py

Output:
    backend/evaluation/eval_report.json
    backend/evaluation/confusion_matrix.png
"""
from __future__ import annotations

# QUAN TRỌNG: Import torch TRƯỚC pandas/sklearn/matplotlib để tránh xung
# đột DLL load order trên Windows (OpenMP/MKL). Nếu import torch sau,
# các thư viện kia sẽ nạp libiomp5md.dll trước → torch load c10.dll fail
# với WinError 1114.
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import torch  # noqa: F401

import asyncio
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

# Cho phép chạy trực tiếp file này (không qua `-m`) bằng cách thêm
# thư mục `backend/` vào sys.path.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from analyzers.sentiment import analyze_texts_async, load_sentiment  # noqa: E402

LABELS = ["positive", "neutral", "negative"]
_DATA_CSV = _BACKEND_DIR / "data" / "eval_crypto_news.csv"
_OUT_DIR = _BACKEND_DIR / "evaluation"
_REPORT_JSON = _OUT_DIR / "eval_report.json"
_CM_PNG = _OUT_DIR / "confusion_matrix.png"


def _load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy file dataset: {path}. "
            f"Hãy tạo file với header: id,headline,label,source"
        )
    df = pd.read_csv(path)
    required = {"id", "headline", "label"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV thiếu cột bắt buộc: {missing}")
    df["label"] = df["label"].astype(str).str.strip().str.lower()
    df = df[df["label"].isin(LABELS)].reset_index(drop=True)
    if df.empty:
        raise ValueError("Dataset rỗng sau khi lọc nhãn hợp lệ")
    return df


async def _predict(headlines: list[str]) -> list[str]:
    """Load sentiment model + dự đoán nhãn cho danh sách headline."""
    load_sentiment()
    results = await analyze_texts_async(headlines)
    return [str(r.get("label", "neutral")).strip().lower() for r in results]


def _compute_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    return {
        "n_samples": len(y_true),
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "precision_macro": round(
            precision_score(
                y_true, y_pred, labels=LABELS, average="macro", zero_division=0
            ),
            4,
        ),
        "recall_macro": round(
            recall_score(
                y_true, y_pred, labels=LABELS, average="macro", zero_division=0
            ),
            4,
        ),
        "f1_macro": round(
            f1_score(
                y_true, y_pred, labels=LABELS, average="macro", zero_division=0
            ),
            4,
        ),
        "labels": LABELS,
    }


def _per_class(y_true: list[str], y_pred: list[str]) -> dict:
    p = precision_score(
        y_true, y_pred, labels=LABELS, average=None, zero_division=0
    )
    r = recall_score(
        y_true, y_pred, labels=LABELS, average=None, zero_division=0
    )
    f = f1_score(
        y_true, y_pred, labels=LABELS, average=None, zero_division=0
    )
    return {
        label: {
            "precision": round(float(p[i]), 4),
            "recall": round(float(r[i]), 4),
            "f1": round(float(f[i]), 4),
        }
        for i, label in enumerate(LABELS)
    }


def _plot_confusion_matrix(
    y_true: list[str], y_pred: list[str], out_path: Path
) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    plt.figure(figsize=(7, 6), dpi=150)
    sns.set_theme(style="white")
    ax = sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=LABELS,
        yticklabels=LABELS,
        cbar=True,
        linewidths=0.5,
        linecolor="#d0d7de",
        annot_kws={"size": 14, "weight": "bold"},
    )
    ax.set_xlabel("Predicted label", fontsize=12, labelpad=10)
    ax.set_ylabel("True label", fontsize=12, labelpad=10)
    ax.set_title(
        "Sentiment Model — Confusion Matrix (Crypto News Eval)",
        fontsize=13,
        weight="bold",
        pad=14,
    )
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


async def _main_async() -> None:
    print(f"[eval] Đọc dataset: {_DATA_CSV}")
    df = _load_dataset(_DATA_CSV)
    headlines = df["headline"].astype(str).tolist()
    y_true = df["label"].tolist()

    print(f"[eval] Chạy sentiment model trên {len(headlines)} mẫu...")
    y_pred = await _predict(headlines)

    metrics = _compute_metrics(y_true, y_pred)
    metrics["per_class"] = _per_class(y_true, y_pred)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with _REPORT_JSON.open("w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        print(f"[eval] Ghi metrics → {_REPORT_JSON}")
    except Exception as e:
        print(f"[eval] Lỗi ghi JSON: {e}")

    try:
        _plot_confusion_matrix(y_true, y_pred, _CM_PNG)
        print(f"[eval] Ghi confusion matrix → {_CM_PNG}")
    except Exception as e:
        print(f"[eval] Lỗi vẽ confusion matrix: {e}")

    print("\n=== KẾT QUẢ ===")
    print(f"Accuracy       : {metrics['accuracy']:.4f}")
    print(f"Precision (macro): {metrics['precision_macro']:.4f}")
    print(f"Recall    (macro): {metrics['recall_macro']:.4f}")
    print(f"F1        (macro): {metrics['f1_macro']:.4f}")


if __name__ == "__main__":
    try:
        asyncio.run(_main_async())
    except FileNotFoundError as e:
        print(f"[eval] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[eval] Lỗi không mong đợi: {e}")
        sys.exit(2)
