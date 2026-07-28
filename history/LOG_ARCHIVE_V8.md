# Pipeline Archive V8

### Entry 32 - 2026-07-13T11:35:00Z

**Action:** Fixed sentiment alignment for ticker-relevant downside headlines, enforced capped risk/reward sizing, and added the 2026 NYSE holiday calendar.

**Changes:**
- `score_headline()` defaults to the configured `MODEL_DIR`, so the Docker-exported FinBERT ONNX model is attempted before the Loughran-McDonald fallback.
- Added business-risk phrase floors for downside headlines such as losing viewers, subscriber loss, customer loss, traffic decline, revenue decline, and churn increases.
- `compute_rolling_sentiment()` applies downside-risk weighting to ticker/company-relevant negative headlines so material bad news cannot be washed out by symmetric positive headline counts.
- Added 2026 NYSE full-day closures and 1:00 PM ET early closes to `config.py`; `check_market_clock()` respects those dates.
- Replaced one-pass maximum-position redistribution with `capped_score_weights()` so BUY allocation weights cannot exceed `MAX_POSITION_WEIGHT` after excess redistribution.

**Logic:** The NFLX roundup mismatch came from aggregation: the displayed headline ("losing viewers") was negative, but symmetric rolling sentiment let several positive headlines offset it into a small positive score. Downside weighting keeps the rolling score aligned with the displayed risk signal, while the capped allocator keeps risk/reward sizing bounded.

**Files Touched:** `config.py`, `engine.py`, `sentiment.py`, `PIPELINE.md`, `README.md`
