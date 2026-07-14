"""Dump news cache to CSV for manual labeling."""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import NEWS_CACHE_FILE

OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "labeled_headlines.csv",
)


def main():
    if not os.path.isfile(NEWS_CACHE_FILE):
        print(f"News cache not found: {NEWS_CACHE_FILE}")
        sys.exit(1)

    with open(NEWS_CACHE_FILE) as f:
        cache = json.load(f)

    headlines = cache.get("headlines", [])
    print(f"Loaded {len(headlines)} headlines from cache")

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "ticker", "net_score", "label"])
        for h in headlines:
            writer.writerow([h["text"], h["ticker"], h["net_score"], ""])

    print(f"Written to {OUTPUT}")
    print(f"  Total: {len(headlines)} headlines")
    print(f"  Zero-score (needs most attention): {sum(1 for h in headlines if h['net_score'] == 0.0)}")
    print()
    print("Next steps:")
    print("  1. Open labeled_headlines.csv in Excel or Google Sheets")
    print("  2. Fill the 'label' column: 0=bearish, 1=neutral, 2=bullish")
    print("  3. Save as CSV and upload to Colab notebook")
    print("  4. Run finetune_colab.ipynb (T4 GPU ~4 min)")


if __name__ == "__main__":
    main()
