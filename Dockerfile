# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12
ARG EXPORT_FINBERT=1

# Stage 1: export FinBERT to ONNX on the builder platform by default.
# Set EXPORT_FINBERT=0 only for a deliberate fallback-only development image.
FROM --platform=$BUILDPLATFORM python:${PYTHON_VERSION}-slim AS model-builder
ARG EXPORT_FINBERT
WORKDIR /app
COPY scripts/export_model.py scripts/export_model.py
RUN if [ "$EXPORT_FINBERT" = "1" ]; then \
      pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir transformers==5.14.1 onnxruntime==1.28.0 onnx==1.22.0 onnxscript==0.7.1 && \
      python scripts/export_model.py; \
    else \
      mkdir -p /app/models; \
    fi

# Stage 2: runtime image. python:3.12-slim is multi-arch and works on OCI Ampere A1.
FROM python:${PYTHON_VERSION}-slim
ARG TARGETPLATFORM
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=model-builder /app/models /app/models
COPY config.py lexicon.py sentiment.py summarizer.py engine.py marketwatch_sync.py bot.py main.py ./

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1 \
    RUN_MODE=COMPETITION

VOLUME ["/app/data"]

CMD ["python", "main.py", "--bot"]
