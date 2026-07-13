"""Export FinBERT to ONNX with INT8 dynamic quantization."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_NAME = "ProsusAI/finbert"
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)


def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    from onnxruntime.quantization import quantize_dynamic, QuantType

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Loading {MODEL_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.eval()

    print("Saving tokenizer...")
    tokenizer.save_pretrained(OUTPUT_DIR)

    print("Exporting to ONNX...")
    dummy_input = tokenizer("Test headline", return_tensors="pt")
    onnx_path = os.path.join(OUTPUT_DIR, "finbert.onnx")

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

    print("Applying INT8 dynamic quantization...")
    quantized_path = os.path.join(OUTPUT_DIR, "finbert_quantized.onnx")
    quantize_dynamic(onnx_path, quantized_path, weight_type=QuantType.QInt8)

    os.remove(onnx_path)
    size_mb = os.path.getsize(quantized_path) / 1e6
    print(f"Quantized model saved: {quantized_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
