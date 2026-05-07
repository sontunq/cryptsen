"""So sánh FinBERT / CryptoBERT / ProjectModel trên eval set.

Usage:
    python backend/training/evaluate.py --model sotunq/crypto-macro-sentiment

In ra bảng accuracy / macro-F1 / confusion matrix cho mỗi model.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from transformers import pipeline

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # project root
EVAL_CSV = ROOT / "backend" / "data" / "eval_crypto_news.csv"
TEST_CSV = HERE / "data" / "test.csv"

LABELS = ("bearish", "neutral", "bullish")


def norm(s: str) -> str:
    s = s.strip().lower()
    if s in ("positive", "bullish", "label_2"):
        return "bullish"
    if s in ("negative", "bearish", "label_0"):
        return "bearish"
    return "neutral"


def load_csv(path: Path, text_col: str, label_col: str) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            t = (r.get(text_col) or "").strip()
            l = (r.get(label_col) or "").strip()
            if t and l:
                texts.append(t)
                labels.append(norm(l))
    return texts, labels


def to_probs(item) -> dict[str, float]:
    probs = {"bearish": 0.0, "neutral": 0.0, "bullish": 0.0}
    labels = item if isinstance(item, list) else [item]
    for p in labels:
        probs[norm(str(p.get("label", "neutral")))] = float(p.get("score", 0.0))
    total = sum(probs.values())
    if total > 0:
        return {k: v / total for k, v in probs.items()}
    return {"bearish": 0.0, "neutral": 1.0, "bullish": 0.0}


def run_model(name: str, hub_id: str, texts: list[str]) -> list[str]:
    print(f"\n>> Loading {name} ({hub_id}) ...")
    device = 0 if torch.cuda.is_available() else -1
    pipe = pipeline(
        "text-classification",
        model=hub_id,
        tokenizer=hub_id,
        device=device,
        truncation=True,
        max_length=256,
        top_k=None,
    )
    preds: list[str] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        results = pipe(chunk, batch_size=batch_size)
        for res in results:
            # top_k=None -> list of dicts sorted by score
            top = res[0] if isinstance(res, list) else res
            preds.append(norm(top["label"]))
    return preds


def run_ensemble(primary_hub_id: str, secondary_hub_id: str, texts: list[str], primary_weight: float) -> list[str]:
    print(
        f"\n>> Loading Ensemble (primary={primary_hub_id}, "
        f"secondary={secondary_hub_id}, w={primary_weight:.2f}) ..."
    )
    device = 0 if torch.cuda.is_available() else -1
    pipe_primary = pipeline(
        "text-classification",
        model=primary_hub_id,
        tokenizer=primary_hub_id,
        device=device,
        truncation=True,
        max_length=256,
        top_k=None,
    )
    pipe_secondary = pipeline(
        "text-classification",
        model=secondary_hub_id,
        tokenizer=secondary_hub_id,
        device=device,
        truncation=True,
        max_length=256,
        top_k=None,
    )

    w = min(1.0, max(0.0, float(primary_weight)))
    preds: list[str] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        r1 = pipe_primary(chunk, batch_size=batch_size)
        r2 = pipe_secondary(chunk, batch_size=batch_size)
        for a, b in zip(r1, r2):
            p1 = to_probs(a)
            p2 = to_probs(b)
            p = {lbl: w * p1[lbl] + (1.0 - w) * p2[lbl] for lbl in LABELS}
            preds.append(max(p, key=p.get))
    return preds


def report(name: str, y_true: list[str], y_pred: list[str]):
    acc = accuracy_score(y_true, y_pred)
    print(f"\n=== {name} ===")
    print(f"Accuracy: {acc:.4f}")
    print(classification_report(y_true, y_pred, labels=list(LABELS), digits=4, zero_division=0))
    cm = confusion_matrix(y_true, y_pred, labels=list(LABELS))
    print("Confusion matrix (rows=true, cols=pred):")
    print("         " + "  ".join(f"{l:>8}" for l in LABELS))
    for lbl, row in zip(LABELS, cm):
        print(f"{lbl:>8} " + "  ".join(f"{v:>8}" for v in row))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=False, help="HF hub id hoặc local path của model fine-tuned")
    ap.add_argument("--dataset", choices=["eval", "test", "both"], default="both")
    ap.add_argument("--ensemble", action="store_true", help="Đánh giá thêm ensemble: ProjectModel + FinBERT")
    ap.add_argument("--ensemble-weight", type=float, default=0.7, help="Trọng số cho ProjectModel trong ensemble")
    args = ap.parse_args()

    datasets = []
    if args.dataset in ("eval", "both") and EVAL_CSV.exists():
        datasets.append(("eval_crypto_news.csv", load_csv(EVAL_CSV, "headline", "label")))
    if args.dataset in ("test", "both") and TEST_CSV.exists():
        datasets.append(("test.csv (held-out)", load_csv(TEST_CSV, "text", "label")))

    if not datasets:
        print("Không tìm thấy dataset nào để eval.")
        return

    models = [
        ("FinBERT", "ProsusAI/finbert"),
        ("CryptoBERT", "ElKulako/cryptobert"),
    ]
    if args.model:
        models.append(("ProjectModel", args.model))

    for ds_name, (texts, y_true) in datasets:
        print(f"\n{'#' * 60}\n# Dataset: {ds_name}  (n={len(texts)})\n{'#' * 60}")
        for m_name, hub_id in models:
            try:
                y_pred = run_model(m_name, hub_id, texts)
                report(f"{m_name} @ {ds_name}", y_true, y_pred)
            except Exception as e:
                print(f"!! {m_name} failed: {e}")

        if args.ensemble and args.model:
            try:
                y_pred = run_ensemble(
                    primary_hub_id=args.model,
                    secondary_hub_id="ProsusAI/finbert",
                    texts=texts,
                    primary_weight=args.ensemble_weight,
                )
                report(
                    f"Ensemble(w={args.ensemble_weight:.2f}) @ {ds_name}",
                    y_true,
                    y_pred,
                )
            except Exception as e:
                print(f"!! Ensemble failed: {e}")


if __name__ == "__main__":
    main()
