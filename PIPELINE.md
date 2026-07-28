## Active Log

### 2026-07-28 06:43 (UTC)
- **Change:** Pinned the model-builder toolchain (`torch==2.13.0+cpu`, `onnx==1.22.0`, and `onnxscript==0.7.1`), made ModernFinBERT export the clean-build default, suppressed only the irrelevant no-PyTorch Transformers advisory at ONNX runtime, rebuilt and recreated the service, then qualified the release with a complete live 75-ticker cycle, automatic bridge recovery across receiver restarts, nine Python tests, four parser fixtures, scorer polarity checks, and final ledger/allocation/resource audits.
- **Reason:** Competition readiness requires reproducible future images and live proof that the scanner, ONNX scorer, MarketWatch heartbeat, dashboard, durable `$100,000` baseline, explicit decision labels, and 10% cash reserve operate together without fallback, stale context, or sustained laptop load.
- **Files:** `Dockerfile`, `README.md`, `PIPELINE.md`

---

### 2026-07-28 06:09 (UTC)
- **Change:** Hardened the competition path end to end: recoverable cash-complete MarketWatch parsing, durable fill journaling and ledger backup, persistent fill-aware execution plans, 21-day sampled sentiment retention, reserve-slot warmup, 10% cash reserve, pinned dependencies, bounded ONNX CPU threads, supervised engine health, read-only `/trades`, and parser/receiver/strategy regression tests.
- **Reason:** The final audit found failure modes that could erase trade context, overwrite live instructions, admit incomplete snapshots, make the 21-day signal impossible, over-allocate cash, hide engine death behind a healthy bot, or silently degrade after a clean rebuild.
- **Files:** `.env.example`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `config.py`, `engine.py`, `main.py`, `marketwatch_sync.py`, `sentiment.py`, `bot.py`, `scripts/export_model.py`, `marketwatch-bridge/`, `tests/`, `README.md`, `history/LOG_ARCHIVE_V17.md`, `PIPELINE.md`

---

### 2026-07-28 02:20 (UTC)
- **Change:** Added intended allocation weight to every BUY row in the Discord scorecard.
- **Reason:** Raw share counts vary with live stock prices and do not represent relative portfolio exposure; the displayed weight makes this auditable without inference.
- **Files:** `engine.py`, `README.md`, `history/LOG_ARCHIVE_V16.md`, `PIPELINE.md`

---

### 2026-07-28 02:10 (UTC)
- **Change:** Renamed the dashboard scorecard columns from `Rank`/`Base` to `Score`/`Health` and documented that live quotes used for order sizing are separate from model signals.
- **Reason:** The former labels could be misread as stale share prices even though they display `adjusted_score` and fundamental `health_score`.
- **Files:** `engine.py`, `README.md`, `history/LOG_ARCHIVE_V15.md`, `PIPELINE.md`

---

### 2026-07-28 01:45 (UTC)
- **Change:** Added alarm-driven Portfolio capture requests with content-script self-recovery after extension reloads, and made the bridge health endpoint calculate stale status from the latest observed snapshot.
- **Reason:** Browser page timers could stop producing captures after an extension reload or inactive page state, while the receiver health endpoint falsely repeated a historical `healthy` value after the five-minute freshness window expired.
- **Files:** `marketwatch-bridge/manifest.json`, `marketwatch-bridge/service-worker.js`, `marketwatch-bridge/content.js`, `marketwatch_sync.py`, `marketwatch-bridge/README.md`, `README.md`, `history/LOG_ARCHIVE_V14.md`, `PIPELINE.md`

---

### 2026-07-27 23:30 (UTC)
- **Change:** Replaced the Linux container news-cycle file lock with an OS-managed advisory lock, retaining the atomic-file fallback for non-Linux direct runs.
- **Reason:** A clean Docker container recreation could leave an atomic lock file behind for up to 90 minutes and suppress the next news cycle despite no active worker.
- **Files:** `engine.py`, `README.md`, `history/LOG_ARCHIVE_V13.md`, `PIPELINE.md`

---

### 2026-07-27 23:05 (UTC)
- **Change:** Changed the local Docker platform default from ARM64 to native AMD64 while preserving the Oracle Ampere ARM64 override.
- **Reason:** Forced ARM emulation on the x86_64 laptop made FinBERT cold initialization take more than four minutes despite healthy ONNX inference.
- **Files:** `.env`, `docker-compose.yml`, `.env.example`, `README.md`, `history/LOG_ARCHIVE_V12.md`, `PIPELINE.md`

---

### 2026-07-27 22:20 (UTC)
- **Change:** Retired chart generation, chart attachments, and the Discord chart command while retaining five-minute numeric portfolio history.
- **Reason:** The MarketWatch bridge and numeric audit history supply the needed execution context; recurring image rendering adds Discord clutter and unnecessary local work.
- **Files:** `config.py`, `engine.py`, `bot.py`, `README.md`, `history/LOG_ARCHIVE_V11.md`, `PIPELINE.md`

---

_Older logs archived in /history/LOG_ARCHIVE_V17.md_
