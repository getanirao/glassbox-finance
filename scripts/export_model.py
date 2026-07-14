"""Export FinBERT to ONNX (quantization skipped when onnx package unavailable)."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-path",
        default="tabularisai/ModernFinBERT",
        help="Model name (HuggingFace hub) or local path to fine-tuned model",
    )
    args = parser.parse_args()

    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Loading {args.model_path}...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_path)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_path)
    model.eval()

    print("Saving tokenizer...")
    tokenizer.save_pretrained(OUTPUT_DIR)

    print("Exporting to ONNX...")
    dummy_input = tokenizer("Test headline", return_tensors="pt")
    onnx_path = os.path.join(OUTPUT_DIR, "finbert.onnx")
    quantized_path = os.path.join(OUTPUT_DIR, "finbert_quantized.onnx")

    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"]),
        onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence"},
            "attention_mask": {0: "batch_size", 1: "sequence"},
            "logits": {0: "batch_size"},
        },
        opset_version=17,
        dynamo=False,
    )

    # Try INT8 quantization, skip if onnx package unavailable
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        print("Applying INT8 dynamic quantization...")
        quantize_dynamic(onnx_path, quantized_path, weight_type=QuantType.QInt8)
        os.remove(onnx_path)
    except Exception:
        import warnings
        warnings.warn("INT8 quantization unavailable - saving unquantized ONNX")
        os.rename(onnx_path, quantized_path)

    size_mb = os.path.getsize(quantized_path) / 1e6
    print(f"Model saved: {quantized_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
