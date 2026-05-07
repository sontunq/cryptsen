import pandas as pd
from transformers import pipeline

def run_mining():
    # 1. Load data
    df = pd.read_csv(r"d:\Final - Đề Án\backend\training\data\test.csv")
    
    # 2. Load model
    model_name = "sotunq/crypto-macro-sentiment"
    print(f"Loading model {model_name}...")
    pipe = pipeline("text-classification", model=model_name, tokenizer=model_name)
    
    # 3. Run predictions
    print("Running inference...")
    texts = df['text'].tolist()
    true_labels = df['label'].tolist()
    
    results = pipe(texts)
    
    hard_examples = []
    for text, true_label, result in zip(texts, true_labels, results):
        pred_label = result['label']
        # We want True = bullish, but Pred = neutral
        if true_label == "bullish" and pred_label != "bullish":
            hard_examples.append((text, pred_label))
            
    print(f"\n--- FOUND {len(hard_examples)} HARD EXAMPLES (True: Bullish, Pred: Neutral/Bearish) ---")
    for i, (txt, pred) in enumerate(hard_examples[:10]):
        print(f"[{i+1}] (Pred: {pred}) {txt}")

if __name__ == "__main__":
    run_mining()
