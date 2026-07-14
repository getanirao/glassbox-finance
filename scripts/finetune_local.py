"""Fine-tune ModernFinBERT on CPU using labeled headlines."""
import os
import sys
import csv
import json
import warnings
import numpy as np

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELED_CSV = os.path.join(PROJECT_ROOT, "labeled_headlines.csv")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "models", "fine_tuned")


def main():
    import torch
    from transformers import (
        AutoTokenizer,
        AutoModelForSequenceClassification,
        TrainingArguments,
        Trainer,
        DataCollatorWithPadding,
    )
    from datasets import Dataset
    from sklearn.model_selection import train_test_split

    # Load labeled data
    print(f"Loading {LABELED_CSV}...")
    with open(LABELED_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["label"].strip()]

    texts = [r["text"] for r in rows]
    labels = [int(r["label"]) for r in rows]
    print(f"Loaded {len(texts)} labeled headlines")

    dist = {0: 0, 1: 0, 2: 0}
    for l in labels:
        dist[l] = dist.get(l, 0) + 1
    print(f"Distribution: bearish={dist[0]} neutral={dist[1]} bullish={dist[2]}")

    # Load model
    MODEL_NAME = "tabularisai/ModernFinBERT"
    print(f"Loading {MODEL_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=3,
        id2label={0: "bearish", 1: "neutral", 2: "bullish"},
        label2id={"bearish": 0, "neutral": 1, "bullish": 2},
    )
    print(f"Model loaded: {model.num_parameters():,} params")

    # Tokenize and split
    def tokenize_fn(batch):
        return tokenizer(batch["text"], truncation=True, max_length=128)

    train_texts, val_texts, train_labels, val_labels = train_test_split(
        texts, labels, test_size=0.15, stratify=labels, random_state=42,
    )

    train_ds = Dataset.from_dict({"text": train_texts, "label": train_labels})
    val_ds = Dataset.from_dict({"text": val_texts, "label": val_labels})
    train_ds = train_ds.map(tokenize_fn, batched=True)
    val_ds = val_ds.map(tokenize_fn, batched=True)
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
    print(f"Train: {len(train_ds)} samples, Val: {len(val_ds)} samples")

    # Training args (CPU)
    training_args = TrainingArguments(
        output_dir=os.path.join(PROJECT_ROOT, "tmp_checkpoints"),
        eval_strategy="epoch",
        save_strategy="epoch",
        learning_rate=2e-5,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        num_train_epochs=5,
        weight_decay=0.01,
        logging_steps=10,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        report_to="none",
        save_total_limit=1,
        dataloader_num_workers=0,
    )

    def compute_metrics(eval_pred):
        predictions = np.argmax(eval_pred[0], axis=-1)
        acc = (predictions == eval_pred[1]).mean()
        return {"accuracy": float(acc)}

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
    )

    print("Training on CPU (this will take ~30-60 min for 763 headlines)...")
    trainer.train()

    metrics = trainer.evaluate()
    print(f"\nValidation accuracy: {metrics['eval_accuracy']:.3f}")
    print(f"Validation loss: {metrics['eval_loss']:.4f}")

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print(f"Model saved to {OUTPUT_DIR}")
    for f in os.listdir(OUTPUT_DIR):
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, f)) / 1e6
        print(f"  {f}: {sz:.1f} MB")

    # Cleanup
    import shutil
    tmp = os.path.join(PROJECT_ROOT, "tmp_checkpoints")
    if os.path.exists(tmp):
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nDone! Next: run 'python scripts/export_model.py --model-path models/fine_tuned'")


if __name__ == "__main__":
    main()
