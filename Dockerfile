# Stage 1: Export FinBERT to ONNX
FROM python:3.13-slim as builder
WORKDIR /app
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install --no-cache-dir transformers onnxruntime onnx onnxscript
COPY scripts/export_model.py scripts/export_model.py
RUN python scripts/export_model.py

# Stage 2: Runtime
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=builder /app/models /app/models
COPY config.py lexicon.py sentiment.py engine.py bot.py main.py ./

RUN mkdir -p /app/data

ENV MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME ["/app/data"]

CMD ["python", "main.py", "--bot"]
