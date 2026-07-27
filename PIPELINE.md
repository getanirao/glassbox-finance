### 2026-07-27 21:08 (UTC)
- **Change:** Reconfigured the MarketWatch bridge for local-only operation through a token-protected `127.0.0.1` Docker receiver and allowed loopback HTTP exclusively in the extension.
- **Reason:** This deployment runs on the user's PC, not an Oracle host; local routing avoids accounts, domains, public ports, and unnecessary network exposure.
- **Files:** `docker-compose.yml`, `.gitignore`, `.env.example`, `marketwatch-bridge.env.example`, `marketwatch-bridge/manifest.json`, `marketwatch-bridge/options.html`, `marketwatch-bridge/options.js`, `marketwatch-bridge/README.md`, `README.md`, `history/LOG_ARCHIVE_V6.md`, `PIPELINE.md`

---

### 2026-07-27 20:46 (UTC)
- **Change:** Allowed MarketWatch baseline establishment when the ledger has only cash-only visualization points, while preserving the hard block for any prior recorded trade.
- **Reason:** A clean competition can accumulate chart refresh history before its first trade; treating that telemetry as execution state would require an unnecessary destructive reset.
- **Files:** `marketwatch_sync.py`, `README.md`, `history/LOG_ARCHIVE_V5.md`, `PIPELINE.md`

---

### 2026-07-27 20:39 (UTC)
- **Change:** Added a passive MarketWatch-to-Glassbox bridge, including an authenticated fail-closed receiver, durable browser outbox, timestamp-preserving activity replay, reconciliation state, dashboard gating, and loopback-only Docker exposure.
- **Reason:** The Wolves workflow needs MarketWatch to remain the sole execution surface while Glassbox receives durable, original-time trade context without Discord commands or speculative position inference.
- **Files:** `marketwatch_sync.py`, `marketwatch-bridge/`, `engine.py`, `config.py`, `main.py`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `README.md`, `ORACLE_ALWAYS_FREE_SETUP.md`, `history/LOG_ARCHIVE_V4.md`, `PIPELINE.md`

---

### 2026-07-27 19:54 (UTC)
- **Change:** Hardened competition-state reset, cache persistence, recommendation gating/sizing, exit tracking, Discord authorization, manual trade validation, and optional article summarization.
- **Reason:** The competition readiness audit found stale-cache restoration, reset races, unconstrained ledger mutations, ineffective allocation limits, repeated partial exits, and documentation/runtime drift.
- **Files:** `config.py`, `engine.py`, `bot.py`, `main.py`, `summarizer.py`, `Dockerfile`, `.env.example`, `README.md`, `sandbox.ps1`, `history/LOG_ARCHIVE_V3.md`, `PIPELINE.md`

---

### Entry 36 — 2026-07-27

**Action:** Added trailing trim and profit-taking exit rules to prevent steady portfolio bleed from loser positions.

**Changes:**
- `config.py`: Added `TRAILING_TRIM_PERCENT=0.05` and `PROFIT_TAKE_PERCENT=0.10`.
- `engine.py`: Rewrote `compute_recommendations()` sell logic — added three new exit tiers before BUY allocation:
  1. **Full stop-loss** (unchanged, -10%): Exit entire position.
  2. **Partial trim** (new, -5%): Sell half of any position down >5% but not at full stop-loss, freeing cash and reducing bleed without fully capitulating.
  3. **Profit-taking** (new, +10%): Sell half of any position up >10%, locking in gains.
  4. **Negative sentiment** (unchanged): Full exit on negative sentiment.
- Renamed `stop_loss_tickers` to `sold_tickers` to reflect multi-role sell tracking.

**Logic:** AMZN at -7% and HAL at -6% were bleeding steadily with no rebalance trigger because they hadn't hit the -10% stop-loss and still had positive sentiment. Now they get trimmed 50% at -5%, reducing exposure to losers while keeping some upside if they recover.

**Files Touched:** `config.py`, `engine.py`, `PIPELINE.md`, `README.md`

---

### Entry 35 — 2026-07-14

**Action:** Added fundamentals cache (24h TTL), market-open scheduler (9:35 AM ET), and Discord alert on LM fallback.

**Changes:**
- `config.py`: Added `FUNDAMENTALS_CACHE_FILE`, `FUNDAMENTALS_CACHE_TTL_HOURS=24`. Bumped `EXECUTION_WINDOW_MINUTES` from 1 to 15.
- `engine.py`: Added `_load_fundamentals_cache()` and `_save_fundamentals_cache()` helpers. Modified `process_ticker()` to check fundamentals cache before fetching `income_stmt`/`balance_sheet`/`stock.info`. If cache is fresh (<24h old), the cached `health_score_raw` and `valuation_multiplier` are used instead of re-fetching from Yahoo Finance. Sentiment and news fetching still run every 60-min cycle regardless.
- `engine.py`: Added market-open scheduler in `_run_loop()` — when market is closed but opens within 60 minutes, sleeps until 9:35 AM ET before triggering the news cycle + evaluation, ensuring recommendations are ready 5 minutes after NYSE open.
- `sentiment.py`: Added `_using_lm` flag to `FinBERTScorer` — set `True` in `_score_lm()`, `False` in `_score_onnx()`. Added `using_lm` property.
- `engine.py`: Added `get_scorer` import from `sentiment`. In `build_competition_dashboard()`, if `get_scorer().using_lm`, prepends `**:warning: SENTIMENT ENGINE DEGRADED — using dictionary fallback**` line — visible within 60 seconds on the dashboard.
- `engine.py`: Added `FUNDAMENTALS_CACHE_FILE` to `handle_reset()` cleanup list.

**Reasoning:**
- yfinance has no official API — it scrapes Yahoo endpoints. Scraping 75 full financial statements every 60 minutes risks IP bans (confirmed by GitHub issues showing blocks at 4-5 daily requests). Fundamentals change quarterly, so 24h caching eliminates 98% of the scraping load without any signal degradation.
- The 1-min execution window was cosmetic but misleading. Bumped to 15 min. The scheduler ensures recs are ready at 9:35 AM ET, catching the first 5 minutes of post-open stability.
- The LM lexicon has 50.1% accuracy on financial news (vs FinBERT's 72.2%, per Kirtac & Germano 2024) and shows no statistically significant relationship with stock returns. If ONNX fails, the system silently degraded to coin-flip quality. The dashboard alert now surfaces this immediately.

**Files Touched:** `config.py`, `sentiment.py`, `engine.py`, `PIPELINE.md`, `README.md`

---

### Entry 34 — 2026-07-13

**Action:** Added LLM-powered article summarization pipeline for enhanced sentiment scoring.

**Changes:**
- Created `summarizer.py` — fetches full article body from news URLs (via BeautifulSoup), then summarizes via configurable LLM provider (OpenAI, Anthropic, or Gemini)
- Added `ENABLE_ARTICLE_SUMMARIZATION`, `SUMMARIZE_PROVIDER`, `SUMMARIZE_MAX_CHARS` to `config.py` (default disabled — requires API key)
- Updated `sentiment_gate()` in `engine.py` to optionally fetch and summarize article body before scoring headline sentiment
- Added `beautifulsoup4>=4.12.0` to `requirements.txt`
- Documented LLM API keys in `.env.example`
- Merged PR #3 (ShadowKingYT444): Oracle ARM deployment, news worker roles, GitHub Actions cron, atomic news locks

**Logical Integration:** When `ENABLE_ARTICLE_SUMMARIZATION=True` and an LLM API key is configured, the engine now scrapes article bodies from news URLs and passes them through the LLM for financial summarization before sentiment scoring. This provides richer context than headlines alone. Default is off to avoid adding API dependencies.

**Files Touched:** `summarizer.py` (new), `config.py`, `engine.py`, `requirements.txt`, `.env.example`, `PIPELINE.md`

---

### Entry 33 — 2026-07-13T11:56:00Z

**Action:** Prepared Oracle Always Free ARM deployment and news-worker roles.

**Changes:**
- Reworked `Dockerfile` for multi-platform/ARM deployment: Python 3.12, `BUILDPLATFORM` model stage, `TARGETPLATFORM` runtime awareness, and opt-in FinBERT export via `EXPORT_FINBERT=1`.
- Updated `docker-compose.yml` for Oracle Ampere defaults (`DOCKER_PLATFORM=linux/arm64`), persistent `glassbox_data`, memory knobs, and an optional `worker` profile for local news-only workers.
- Added `--engine`, `--news-worker`, and `--news-worker-once` CLI roles in `main.py`.
- Added `run_news_worker()` and `send_roundup=False` support so workers fetch/score news without Discord dashboards or recommendations.
- Hardened the local news lock with atomic file creation, owner tokens, and stale-lock cleanup for same-volume engine/worker coordination.
- Added scheduled/manual GitHub Actions workflow `.github/workflows/news-worker.yml` to run `--news-worker-once` and preserve cache artifacts until shared storage is wired.
- Added root setup/handoff docs: `ORACLE_ALWAYS_FREE_SETUP.md` and `POSTGRES_STORAGE_HANDOFF.md`.

**Logic:** Oracle Ampere A1 is the always-on host for bot + recommendation engine. Worker roles leave room for future distributed cache builders without duplicate Discord posts. FinBERT export is opt-in to avoid PyTorch build pressure on ARM free-tier hosts; the existing LM fallback remains available.

**Files Touched:** `Dockerfile`, `docker-compose.yml`, `.env.example`, `.github/workflows/news-worker.yml`, `config.py`, `main.py`, `engine.py`, `README.md`, `PIPELINE.md`, `ORACLE_ALWAYS_FREE_SETUP.md`, `POSTGRES_STORAGE_HANDOFF.md`

---

### Entry 32 — 2026-07-13T11:35:00Z

**Action:** Fixed sentiment alignment for ticker-relevant downside headlines, enforced capped RR sizing, and added the 2026 NYSE holiday calendar.

**Changes:**
- `score_headline()` now defaults to the configured `MODEL_DIR`, so the Docker-exported FinBERT ONNX model is actually attempted before falling back to the Loughran-McDonald lexicon.
- Added business-risk phrase floors for downside headlines such as losing viewers, subscriber loss, customer loss, traffic decline, revenue decline, and churn increases.
- `compute_rolling_sentiment()` now applies downside-risk weighting to ticker/company-relevant negative headlines so material bad news cannot be washed out by symmetric positive headline counts.
- Added 2026 NYSE full-day closures and 1:00 PM ET early closes to `config.py`; `check_market_clock()` now respects those dates.
- Replaced one-pass max-position redistribution with `capped_score_weights()` so BUY allocation weights cannot exceed `MAX_POSITION_WEIGHT` after excess redistribution.

**Logic:** The NFLX roundup mismatch came from aggregation: the displayed headline ("losing viewers") was negative, but symmetric rolling sentiment let several positive headlines offset it into a small positive score. The new downside weighting makes ticker-relevant negative news dominate enough to keep the rolling score aligned with the displayed risk signal, while the capped allocator keeps risk/reward sizing bounded.

**Files Touched:** `config.py`, `engine.py`, `sentiment.py`, `PIPELINE.md`, `README.md`

---

### Entry 31 — 2026-07-12T22:00:00Z

**Action:** Removed SKIP rows from dashboard; capped BUY recommendations to top 6 to prevent capital dilution.

**Changes:**
- **SKIP eliminated**: Negative-sentiment tickers are now filtered out of `predicted` entirely in `compute_recommendations()`. Only sentiment ≥ 0.0 tickers appear in the dashboard allocation table.
- **MAX_BUYS_PER_CYCLE = 6**: Only the top 6 eligible tickers (by adjusted_score) receive BUY recommendations. Held tickers past position 6 get HOLD. Tickers that dropped out or turned negative get SELL.
- **Return type changed**: `compute_recommendations()` now returns `(recs, display_list)` where `display_list` is the sentiment-filtered predicted list, which is passed to the dashboard instead of the raw top-12.

**Logic:** Previously 12 BUY rows diluted capital to ~$8,333 each. Now the top 6 split available cash score-weightedly. Example: with $100k cash and scores [120, 120, 120, 120, 97, 92], allocations are ~$19.6k, $19.6k, $19.6k, $19.6k, $15.9k, $15.1k — concentrated in the strongest signals. Negative sentiment tickers like GOOGL (-0.184), JNJ (-0.322), AMZN (-0.215) no longer appear at all.

**Files Touched:** `config.py`, `engine.py`, `PIPELINE.md`, `README.md`

---

_Older logs archived in /history/LOG_ARCHIVE_V6.md_
