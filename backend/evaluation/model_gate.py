"""Model gate checklist for objective sentiment-model acceptance.

Usage examples:
  python -m evaluation.model_gate --model sotunq/crypto-macro-sentiment
  python -m evaluation.model_gate --model ./local_model_dir --no-baselines

Outputs:
  backend/evaluation/model_gate_report.json

The script evaluates on:
  - backend/data/eval_crypto_news.csv
  - backend/training/data/test.csv

And applies pass/fail gates:
  1. Minimum sample size
  2. Macro F1 threshold
  3. Per-class minimum recall
  4. Positive/Bullish recall threshold
  5. Bootstrap CI lower bound for macro F1
  6. Optional: beats FinBERT on combined set by delta
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from transformers import pipeline

ROOT = Path(__file__).resolve().parent.parent
EVAL_CSV = ROOT / "data" / "eval_crypto_news.csv"
TEST_CSV = ROOT / "training" / "data" / "test.csv"
OUT_JSON = ROOT / "evaluation" / "model_gate_report.json"

LABELS = ("bearish", "neutral", "bullish")


def _norm_label(raw: str) -> str:
    s = str(raw).strip().lower()
    if s in ("positive", "bullish", "label_2"):
        return "bullish"
    if s in ("negative", "bearish", "label_0"):
        return "bearish"
    return "neutral"


def _load_csv(path: Path, text_col: str, label_col: str) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    if not path.exists():
        return texts, labels

    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = (row.get(text_col) or "").strip()
            label = _norm_label(row.get(label_col) or "")
            if text:
                texts.append(text)
                labels.append(label)
    return texts, labels


def _to_probs(item) -> dict[str, float]:
    probs = {"bearish": 0.0, "neutral": 0.0, "bullish": 0.0}
    entries = item if isinstance(item, list) else [item]
    for p in entries:
        lbl = _norm_label(p.get("label", "neutral"))
        probs[lbl] = float(p.get("score", 0.0))
    total = sum(probs.values())
    if total <= 0:
        return {"bearish": 0.0, "neutral": 1.0, "bullish": 0.0}
    return {k: v / total for k, v in probs.items()}


def _predict(model_id: str, texts: list[str], max_length: int = 256) -> list[str]:
    if not texts:
        return []

    device = 0 if torch.cuda.is_available() else -1
    clf = pipeline(
        "text-classification",
        model=model_id,
        tokenizer=model_id,
        device=device,
        truncation=True,
        max_length=max_length,
        top_k=None,
    )

    y_pred: list[str] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        outputs = clf(chunk, batch_size=batch_size)
        for out in outputs:
            probs = _to_probs(out)
            y_pred.append(max(probs, key=probs.get))
    return y_pred


def _metrics(y_true: list[str], y_pred: list[str]) -> dict:
    p, r, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=list(LABELS),
        average=None,
        zero_division=0,
    )
    macro = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=list(LABELS),
        average="macro",
        zero_division=0,
    )
    return {
        "n_samples": len(y_true),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(macro[0]),
        "recall_macro": float(macro[1]),
        "f1_macro": float(macro[2]),
        "per_class": {
            lbl: {
                "precision": float(p[i]),
                "recall": float(r[i]),
                "f1": float(f1[i]),
            }
            for i, lbl in enumerate(LABELS)
        },
        "pred_distribution": dict(Counter(y_pred)),
        "true_distribution": dict(Counter(y_true)),
    }


def _bootstrap_ci_macro_f1(
    y_true: list[str], y_pred: list[str], n_boot: int = 1000, seed: int = 42
) -> tuple[float, float]:
    if not y_true:
        return 0.0, 0.0

    rng = random.Random(seed)
    n = len(y_true)
    f1_values: list[float] = []
    indices = list(range(n))
    for _ in range(n_boot):
        boot = [indices[rng.randrange(0, n)] for _ in range(n)]
        yt = [y_true[i] for i in boot]
        yp = [y_pred[i] for i in boot]
        f1 = precision_recall_fscore_support(
            yt,
            yp,
            labels=list(LABELS),
            average="macro",
            zero_division=0,
        )[2]
        f1_values.append(float(f1))

    lo, hi = np.percentile(f1_values, [2.5, 97.5])
    return float(lo), float(hi)


def _gate(
    combined_metrics: dict,
    ci_lo: float,
    baseline_finbert_f1: float | None,
    rules: dict,
) -> dict:
    rec = combined_metrics["per_class"]
    checks = [
        {
            "name": "min_samples",
            "pass": combined_metrics["n_samples"] >= rules["min_samples"],
            "actual": combined_metrics["n_samples"],
            "target": f">= {rules['min_samples']}",
        },
        {
            "name": "macro_f1",
            "pass": combined_metrics["f1_macro"] >= rules["min_macro_f1"],
            "actual": round(combined_metrics["f1_macro"], 4),
            "target": f">= {rules['min_macro_f1']}",
        },
        {
            "name": "min_class_recall",
            "pass": min(rec[l]["recall"] for l in LABELS) >= rules["min_class_recall"],
            "actual": round(min(rec[l]["recall"] for l in LABELS), 4),
            "target": f">= {rules['min_class_recall']}",
        },
        {
            "name": "bullish_recall",
            "pass": rec["bullish"]["recall"] >= rules["min_bullish_recall"],
            "actual": round(rec["bullish"]["recall"], 4),
            "target": f">= {rules['min_bullish_recall']}",
        },
        {
            "name": "macro_f1_ci_lower",
            "pass": ci_lo >= rules["min_ci_lower_macro_f1"],
            "actual": round(ci_lo, 4),
            "target": f">= {rules['min_ci_lower_macro_f1']}",
        },
    ]

    if baseline_finbert_f1 is not None:
        delta = combined_metrics["f1_macro"] - baseline_finbert_f1
        checks.append(
            {
                "name": "beat_finbert_delta_macro_f1",
                "pass": delta >= rules["min_delta_vs_finbert"],
                "actual": round(delta, 4),
                "target": f">= {rules['min_delta_vs_finbert']}",
            }
        )

    return {
        "overall_pass": all(c["pass"] for c in checks),
        "checks": checks,
    }


def _concat(*parts: tuple[list[str], list[str]]) -> tuple[list[str], list[str]]:
    t_all: list[str] = []
    y_all: list[str] = []
    for texts, labels in parts:
        t_all.extend(texts)
        y_all.extend(labels)
    return t_all, y_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Objective sentiment-model gate")
    parser.add_argument("--model", required=True, help="HF hub id hoặc local model path")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument(
        "--no-baselines",
        action="store_true",
        help="Tắt so sánh FinBERT baseline",
    )
    args = parser.parse_args()

    eval_set = _load_csv(EVAL_CSV, "headline", "label")
    test_set = _load_csv(TEST_CSV, "text", "label")
    all_texts, all_labels = _concat(eval_set, test_set)

    if not all_texts:
        raise RuntimeError("Không có dữ liệu eval/test để chạy model gate.")

    rules = {
        "min_samples": 300,
        "min_macro_f1": 0.78,
        "min_class_recall": 0.68,
        "min_bullish_recall": 0.72,
        "min_ci_lower_macro_f1": 0.72,
        "min_delta_vs_finbert": 0.01,
    }

    print(f"[gate] Evaluate model: {args.model}")
    y_pred_eval = _predict(args.model, eval_set[0], max_length=args.max_length)
    y_pred_test = _predict(args.model, test_set[0], max_length=args.max_length)
    y_pred_all = y_pred_eval + y_pred_test

    metrics_eval = _metrics(eval_set[1], y_pred_eval)
    metrics_test = _metrics(test_set[1], y_pred_test)
    metrics_all = _metrics(all_labels, y_pred_all)

    ci_lo, ci_hi = _bootstrap_ci_macro_f1(
        all_labels, y_pred_all, n_boot=args.n_boot, seed=args.seed
    )

    finbert_f1 = None
    if not args.no_baselines:
        print("[gate] Evaluate baseline: ProsusAI/finbert")
        yb = _predict("ProsusAI/finbert", all_texts, max_length=args.max_length)
        finbert_f1 = _metrics(all_labels, yb)["f1_macro"]

    gate = _gate(metrics_all, ci_lo, finbert_f1, rules)

    report = {
        "model": args.model,
        "datasets": {
            "eval_csv": str(EVAL_CSV),
            "test_csv": str(TEST_CSV),
        },
        "rules": rules,
        "metrics": {
            "eval": metrics_eval,
            "test": metrics_test,
            "combined": metrics_all,
        },
        "bootstrap_ci_macro_f1_95": {
            "lower": round(ci_lo, 4),
            "upper": round(ci_hi, 4),
        },
        "baseline": {
            "finbert_macro_f1_combined": (
                round(finbert_f1, 4) if finbert_f1 is not None else None
            )
        },
        "gate": gate,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n=== MODEL GATE SUMMARY ===")
    print(f"Combined macro-F1: {metrics_all['f1_macro']:.4f}")
    print(f"Combined accuracy: {metrics_all['accuracy']:.4f}")
    print(f"Macro-F1 95% CI:   [{ci_lo:.4f}, {ci_hi:.4f}]")
    if finbert_f1 is not None:
        delta = metrics_all["f1_macro"] - finbert_f1
        print(f"Delta vs FinBERT:  {delta:+.4f}")
    print(f"Gate pass:         {gate['overall_pass']}")
    print(f"Report JSON:       {OUT_JSON}")


if __name__ == "__main__":
    main()
