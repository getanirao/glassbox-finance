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

### Entry 30 — 2026-07-12T21:00:00Z

**Action:** Added sentiment gate on BUY decisions and score-weighted allocation from available cash.

**Changes:**
- **Sentiment gate**: `compute_recommendations()` now checks `sentiment >= SENTIMENT_BUY_THRESHOLD` (default 0.0) before issuing a BUY. Tickers in the top 12 with negative sentiment show as **SKIP** (0 target shares) instead of BUY.
- **Score-weighted allocation**: Instead of equal split of STARTING_CAPITAL, new BUY candidates split `cash_balance` proportionally by `adjusted_score`. Higher-scored tickers get more capital.
- **Dashboard alignment**: Allocation section now uses a `rec_map` dict lookup so SKIP and BUY rows render in correct predicted-score order regardless of recommendation generation order.
- Added `SENTIMENT_BUY_THRESHOLD = 0.0` to `config.py`.

**Logic:** Previously a ticker with negative sentiment like JNJ (-0.322) would still get a BUY if it ranked in the top 12 by adjusted_score. Now BUY requires positive (or neutral) sentiment. Allocation is score-weighted so GOOGL (113.4) gets more cash than HAL (86.6), not equal splits.

**Files Touched:** `config.py`, `engine.py`, `PIPELINE.md`, `README.md`

---

### Entry 29 — 2026-07-12T20:00:00Z

**Action:** Applied temperature scaling (T=0.5) to FinBERT ONNX logits to sharpen compressed sentiment scores.

**Changes:**
- Added `FINBERT_TEMPERATURE = 0.5` to `config.py`
- In `_score_onnx()`, logits are divided by T before softmax: `logits = logits / 0.5`
- T < 1 redistributes neutral probability mass to the winning class, correcting FinBERT's conservative bias on mildly-toned financial headlines
- Example effect: "Should You Buy Microsoft Stock?" → net +0.28→+0.50; "Here's Why Salesforce is One of the Best" → +0.34→+0.62
- Existing cache headlines re-scored via `repair_news_cache()` on next startup

**Research Basis:** Temperature scaling (Guo et al. 2017, 3,000+ citations) is the standard post-hoc calibration method. T=0.5 chosen as inverse temperature (sharpening) to compensate for FinBERT's 3-class output where neutral probability compresses the pos-neg spread. No calibration set required — T=0.5 provides approximately 2× slope near zero.

**Files Touched:** `config.py`, `sentiment.py`, `PIPELINE.md`, `README.md`

---

### Entry 28 — 2026-07-12T16:00:00Z

**Action:** Added ROE + P/E (or P/B for banks) valuation multiplier to ticker scoring pipeline.

**Changes:**
- **Added** valuation multiplier in `process_ticker()` after solvency evaluation, before sentiment penalty
- ROE factor: `max(0.5, min(1.5, roe / 0.20))` — 20% ROE = 1.0× par, capped 0.5–1.5×
- **Non-banks** (70 tickers): P/E blended 50/50 with ROE — P/E <5→0.7, 5–10→0.9, 10–20→1.0, 20–40→0.9, >40→0.8
- **Banks** (JPM, GS, BAC, MS, C): P/B blended 70/30 with ROE — P/B <0.8→0.8, 0.8–1.0→0.9, 1.0–1.5→1.0, 1.5–2.0→0.9, >2.0→0.85
- Added `valuation_multiplier` to return dict and status print for dashboard visibility
- Research-backed: Novy-Marx (2013, 4,000+ citations) confirms profitability and value are complementary (~0.1 correlation). Equal-weight (50/50) per academic consensus avoids overfitting. Banks use P/B per Investopedia/BankSift/BIS guidance.

**Files Touched:** `engine.py`, `PIPELINE.md`, `README.md`

---

### Entry 27 — 2026-07-12T09:00:00Z

**Action:** Stripped SANDBOX mode and observation state machine; competition-only architecture with real trade logging.

**Changes:**
- **Removed** SANDBOX mode entirely — dropped `load_sandbox_ledger`, `save_sandbox_ledger`, `sandbox_execute`, `display_portfolio_table`, `build_sandbox_status`, `build_master_payload`, `send_master_report`
- **Removed** observation state machine — dropped `load_observation_state`, `save_observation_state`, `collect_spot_prices`, `compute_volatility_spread`, `volatility_stabilized`, `OBSERVATION_FILE`
- **Added** competition ledger infrastructure — `load_competition_ledger()`, `save_competition_ledger()`, `record_trade()`, `record_hold()` in `engine.py`
- **Added** competition dashboard — `build_competition_dashboard()`, `send_or_update_comp_dashboard()`, `generate_competition_chart()`, `COMPETITION_CHART`, `COMPETITION_MESSAGE_STATE`, `COMPETITION_PREDICTION_FILE`
- **Added** `/trade` (ticker, buy/sell, shares, price) and `/hold` (ticker) slash commands to `bot.py`
- **Unified** `_run_loop()` to single COMPETITION path: 60-min news + full eval always runs regardless of market state, 60-sec viz loop updates portfolio value + chart + dashboard
- **Final recommendations** issued only when gate expired + market open, with `EXECUTE BY HH:MM UTC` timestamp and `/trade` command template
- **Fixed** `INSTITUTIONAL_BANKS` undefined bug — added `{"JPM","GS","BAC","MS","C"}` to `config.py`
- **Tuned** time constants: `LONG_WINDOW_HOURS 168→504`, `DECAY_HALF_LIFE_HOURS 72→336`
- **Updated** `handle_reset()` to clear competition state files + chart

**Files Touched:** `config.py`, `engine.py`, `bot.py`, `PIPELINE.md`, `README.md`

---

### Entry 26 — 2026-07-12T08:35:00Z

**Action:** Replaced hardcoded sentiment lexicons with Loughran-McDonald Master Dictionary (Journal of Finance, 2011).

**Changes:**
- Created `lexicon.py` — auto-generated module with 380 positive words (347 from LM + 33 headline additions) and 2364 negative words (2345 from LM + 19 headline additions).
- Reduced `config.py` — removed hardcoded POSITIVE_LEXICON, NEGATIVE_LEXICON, CRITICAL_NEGATIVE_LEXICON sets; now imports from `lexicon.py`.
- Updated `Dockerfile` to COPY `lexicon.py` into the image.
- Kept custom `CRITICAL_NEGATIVE_LEXICON` (10 words) for the weight boost mechanism — unchanged.
- `gen_lexicon.py` preserved in repo for reproducibility.

**Impact:**
- Old lexicon: ~96 words (44 positive, 52 negative).
- New lexicon: ~2744 words (380 positive, 2364 negative) — **28× larger**.
- 154 cache headlines auto-corrected on first boot with expanded detection.
- Words like "abandon", "impair", "litigation", "restate" now caught — previously missed entirely.

**Files Touched:** `lexicon.py` (new), `config.py`, `Dockerfile`, `gen_lexicon.py` (new), `PIPELINE.md`, `README.md`

---

_Older logs archived in /history/LOG_ARCHIVE_V2.md_
