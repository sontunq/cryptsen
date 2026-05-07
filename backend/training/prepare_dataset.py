"""Build crypto sentiment dataset (SIMPLIFIED).

Nguon:
  - ExponentialScience/DLT-Sentiment-News    (crypto news, market_direction)
  - TimKoornstra/financial-tweets-sentiment  (financial tweets - them mau bearish)
  - source/coindesk_seed.csv + coindesk_hard_examples.csv (hand-curated)

Sau khi gom, cap CAP_PER_CLASS moi lop de can bang.

Output: data/{train,val,test}.csv  (cols: text, label)
"""
from __future__ import annotations

import csv
import random
import re
from pathlib import Path

from datasets import load_dataset
from sklearn.model_selection import train_test_split

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
SRC = HERE / "source"
OUT.mkdir(exist_ok=True)

SEED = 42
LABELS = ("bearish", "neutral", "bullish")
CAP_PER_CLASS = 5000
_URL_RE = re.compile(r"https?://")
random.seed(SEED)


def _norm(label) -> str:
    s = str(label).strip().lower()
    if s in ("bullish", "bull", "positive", "2"):
        return "bullish"
    if s in ("bearish", "bear", "negative"):
        return "bearish"
    return "neutral"


def load_dlt_news() -> list[tuple[str, str]]:
    print("[1] DLT-Sentiment-News ...")
    ds = load_dataset("ExponentialScience/DLT-Sentiment-News", split="train")
    rows = []
    for r in ds:
        text = (r.get("text") or r.get("title") or "").strip()
        label = r.get("market_direction")
        if text and label:
            rows.append((text, _norm(label)))
    print(f"    -> {len(rows)} samples")
    return rows


def load_financial_tweets() -> list[tuple[str, str]]:
    """38k tweets tai chinh, them mau bearish de can bang."""
    print("[2] Financial tweets ...")
    ds = load_dataset("TimKoornstra/financial-tweets-sentiment", split="train")
    mapping = {0: "neutral", 1: "bullish", 2: "bearish"}
    rows = []
    for r in ds:
        text = (r.get("tweet") or "").strip()
        label = r.get("sentiment")
        if text and label in mapping:
            rows.append((text, mapping[label]))
    print(f"    -> {len(rows)} samples")
    return rows


def load_curated(filename: str, tag: str) -> list[tuple[str, str]]:
    f = SRC / filename
    if not f.exists():
        print(f"    ! {filename} not found")
        return []
    rows = []
    with f.open(encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            text = (r.get("text") or "").strip()
            label = (r.get("label") or "").strip()
            if text and label:
                rows.append((text, _norm(label)))
    print(f"    -> {tag}: {len(rows)} samples")
    return rows


def main():
    rows = load_dlt_news()
    rows += load_financial_tweets()
    print("[3] Hand-curated ...")
    rows += load_curated("coindesk_seed.csv", "seed")
    rows += load_curated("coindesk_hard_examples.csv", "hard")

    # Lam sach: bo URL spam, qua ngan, va dedupe
    seen, clean = set(), []
    for t, l in rows:
        if _URL_RE.search(t) or len(t.strip()) < 20:
            continue
        key = t.lower().strip()
        if key not in seen:
            seen.add(key)
            clean.append((t, l))

    # Cap moi class de can bang
    buckets = {lbl: [(t, l) for t, l in clean if l == lbl] for lbl in LABELS}
    balanced = []
    for lbl, items in buckets.items():
        random.shuffle(items)
        balanced.extend(items[:CAP_PER_CLASS])
    random.shuffle(balanced)

    dist = {lbl: sum(1 for _, l in balanced if l == lbl) for lbl in LABELS}
    print(f"\nTotal: {len(balanced)}")
    print(f"Distribution: {dist}")

    # Split 80/10/10 stratified
    texts, labels = zip(*balanced)
    X_tmp, X_test, y_tmp, y_test = train_test_split(
        texts, labels, test_size=0.1, stratify=labels, random_state=SEED,
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_tmp, y_tmp, test_size=0.111, stratify=y_tmp, random_state=SEED,
    )

    for name, X, y in [("train", X_train, y_train),
                       ("val", X_val, y_val),
                       ("test", X_test, y_test)]:
        with (OUT / f"{name}.csv").open("w", encoding="utf-8", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["text", "label"])
            w.writerows(zip(X, y))
        print(f"  -> {name}.csv: {len(X)} rows")


if __name__ == "__main__":
    main()
