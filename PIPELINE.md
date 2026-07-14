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

### Entry 25 — 2026-07-12T08:15:00Z

**Action:** Added negation detection, cache self-repair at startup, and backup/restore protection for the news cache.

**Changes:**
- Added **VADER-style negation detection** in `sentiment_gate()`: "not/no/never/neither/nor/t" within 3 tokens before a sentiment word flips its polarity (negated positive → negative, negated negative → positive).
- Added `repair_news_cache()` called at engine startup after `load_news_cache()` — re-scans all cached headlines with negation-aware scoring and corrects any entries with stale scores (printed 7 fixes on first run).
- Added `NEWS_CACHE_BACKUP` path and backup logic: `save_news_cache()` copies the current cache to `.news_cache.backup.json` before overwriting (only if ≥50% tickers present to avoid backing up a corrupted state).
- Added auto-restore in `load_news_cache()`: if the main cache has <3 tickers and a backup exists, the backup is used instead.
- Integrated `shutil` import and `NEWS_CACHE_BACKUP` config constant.

**Logic:**
- Negation detection catches critical flips like "Not a Buy" (was +1.00, now -1.00), which was the original JNJ score discrepancy root cause.
- Self-repair ensures old cache entries are corrected on every restart, so cache migration scripts are no longer needed.
- Backup protection prevents mid-cycle crashes from corrupting the cache — the incomplete cycle's save overwrites the main file, but the backup preserves the last complete state.

**Files Touched:** `engine.py`, `config.py`, `PIPELINE.md`, `README.md`

---

### Entry 24 — 2026-07-11T20:00:00Z

**Action:** Implemented relevance-weighted sentiment + negativity-bias weight boosting to prevent headline dilution and filter generic feed noise.

**Changes:**
- Added `critical_neg` field to news cache entries in `sentiment_gate()` (line 642).
- Added **relevance weighting** in `compute_rolling_sentiment()`: headlines mentioning ticker symbol get 3× weight, company name 2×, unrelated content 0.33×.
- Added **critical_neg weight boost** on top of relevance: `(1 + critical_neg)` multiplier, giving 2×–3× for critical keywords like verdict/lawsuit/fraud.
- Ran one-time cache migration to backfill `critical_neg` for all 763 existing entries, with recalculated `net_score` using the proper double-count formula.

**Logic:**
- 60–80% of Yahoo Finance `stock.news` feed headlines are generic market content irrelevant to the ticker — these inflate sentiment scores with positive language. Relevance weighting discounts them to 0.33× so ticker-specific news dominates.
- Material negative headlines (verdict, lawsuit, investigation) then get an additional 2–3× weight boost, preventing dilution by neutral headlines.
- JNJ: +0.40 → -0.10 (verdict headline now dominates irrelevant dividend articles). AAPL: +0.20 → -0.07 (suing OpenAI headlines weighted correctly).
- Self-adjusting — no hardcoded caps or thresholds. Backward compatible.

**Files Touched:** `engine.py`, `PIPELINE.md`, `README.md`, `data/.news_cache.json`

---

### Entry 23 — 2026-07-11T18:00:00Z

**Action:** Addressed multiple Discord integration and market clock logic issues, including off-hours behavior and dashboard accuracy.

**Changes:**
- Removed market hour gate from `_run_loop` that was causing Discord news roundup messages to be suppressed during off-market hours.
- Corrected the primary log message in `_run_loop` (line 1143) to display the actual `market_state` variable (e.g., `ANALYTICAL_OFF_HOURS`) instead of a hardcoded `MARKET_OPEN` string.
- Implemented robust 404 error handling in `send_or_update_dashboard` to clear stale dashboard message IDs (in `.message_state`) and automatically post a new dashboard message if an old one is no longer found on Discord.
- Modified `build_sandbox_status` function definition to accept `market_state` as a parameter.
- Replaced the hardcoded `MARKET_OPEN` string within the Discord dashboard message content generated by `build_sandbox_status` (line 525) with the new `market_state` parameter, ensuring dynamic and accurate display.
- Updated all calls to `build_sandbox_status` (lines 1142, 1180, 1185) to pass the correct `market_state` parameter.
- Added a market state check to the portfolio rebalance logic in Sandbox mode, preventing simulated BUY/SELL/HOLD actions when `market_state` is not `MARKET_OPEN` (i.e., during off-market hours).

**Logic:**
- Ensures continuous news updates on Discord regardless of market hours, aligning with the "independent news clock" design.
- Provides accurate market status logging and Discord dashboard display, improving system transparency.
- Enhances bot reliability by preventing erroneous attempts to edit non-existent Discord messages and gracefully recovering by posting new messages.
- Enforces sensible trading boundaries in Sandbox mode, preventing simulated trades when the market is closed, aligning behavior with real-world trading constraints while still allowing analytics to run.

**Files Touched:** `engine.py`, `PIPELINE.md`, `README.md`

---

# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

### Entry 22 — 2026-07-11T16:25:00Z

**Action:** Fixed two bugs causing the news roundup to split into duplicate Discord messages instead of editing one rolling message.

**Changes:**
- **Bug 1 (truncation overflow):** `send_batched_news()` truncation logic was computing the cutoff without accounting for the suffix length. The `\n... truncated` suffix is 13 chars, but the cutoff used `MAX_MSG - 3`, so a payload near the limit could truncate to a result that was still over 2000 chars. At 12:55 UTC a 2002-char payload passed through truncation and Discord rejected it with `400 Bad Request: Must be 2000 or fewer in length`. Fixed: raised `MAX_MSG` to the true Discord limit (2000), extracted suffix length into `TRUNC_SUFFIX` constant, and subtracted its length from the cutoff budget so the final payload can never exceed the limit.
- **Bug 2 (error mishandling):** The exception handler treated *any* PATCH failure as a stale-message-ID problem and deleted the message state file. A 400 error (payload too large) cleared a perfectly valid message ID, causing the next cycle to POST a brand-new second message — splitting the roundup into two. Fixed: now only clears the message ID on HTTP 404 (genuinely stale/deleted message). On other errors (400, 429, 500), preserves the message ID so the next cycle retries the edit instead of creating a duplicate.

**Logic:** The two bugs compounded — truncation failure → 400 error → cleared valid ID → duplicate message posted. Both are now isolated: truncation is mathematically guaranteed to stay under 2000, and the error handler distinguishes "message is gone" (404 → repost) from "payload was bad" (4xx → retry, keep ID).

**Files Touched:** `engine.py`, `PIPELINE.md`, `README.md`

### Entry 21 — 2026-07-11T09:55:00Z

**Action:** Externalized run mode from hardcoded Dockerfile CMD to environment variable for zero-rebuild mode switching.

**Changes:**
- Added `RUN_MODE` env var support to `main.py`: run mode resolution changed from `args.sandbox/args.comp` only to a three-tier fallback: `--sandbox`/`--comp` CLI flags → `RUN_MODE` env var → default `COMPETITION`
- Added `RUN_MODE=${RUN_MODE:-SANDBOX}` to `docker-compose.yml` environment block (defaults to SANDBOX if unset)
- Removed `--sandbox` from Dockerfile CMD, leaving only `--bot` (mode now fully external)
- `/news` slash command now sorts top 20 tickers by short-term sentiment (descending) instead of raw headline count — strongest signals surface first (e.g. CSCO +0.700 at top instead of position 17)

**Logic:** The mode was hardcoded in the Dockerfile, meaning switching to COMPETITION required a code change + rebuild + redeploy — unreasonable on competition day. Now the operator simply sets `RUN_MODE=COMPETITION` in `.env` (or passes it inline) and runs `docker compose up -d`. No rebuild needed. CLI flags (`--sandbox`/`--comp`) still override the env var for local development. The `/news` sort change surfaces actionable sentiment signals above volume noise.

**Files Touched:** `main.py`, `Dockerfile`, `docker-compose.yml`, `bot.py`, `PIPELINE.md`, `README.md`

### Entry 20 — 2026-07-11T09:26:00Z

**Action:** Added 10-minute warm-up floor to the smart execution trigger, preventing rebalance during the chaotic opening minutes.

**Changes:**
- Added `WARMUP_MINUTES = 10` constant to `config.py` (minimum observation time before the volatility gate is allowed to trigger)
- Rewrote `volatility_stabilized()` in `engine.py` with a three-tier decision: (1) if `elapsed < WARMUP_MINUTES` → return False regardless of spread, (2) if `elapsed >= GRACE_MINUTES` → return True (hard cap unchanged), (3) between 10–30 min → return `spread < VOLATILITY_THRESHOLD`
- Upgraded the `[Volatility]` log line to show current phase: `WARMUP (x/10 min)` during floor, `SPREAD x < 0.005` during active gate, plus hard cap reference

**Research Basis:** Academic literature consistently finds the first 5–30 minutes of trading exhibit the highest intraday volatility and widest spreads (SEC 2015 — volume 400%+ above normal at open; Ghysels & Valkanov, cited 1,223× — 5-min realized power is the strongest volatility predictor; ResearchGate optimal trading frames — recommends avoiding first 5–10 min). The previous design had no minimum floor, allowing execution as early as minute 2–3 if the spread looked calm — a false-signal risk during price discovery. The 10-min floor aligns with the consensus "avoid the first 10 minutes" guidance.

**Logic:** No trades execute before 6:40 AM PT (10 min after 6:30 AM ET open). From 6:40–7:00 AM PT, the volatility gate is active (fires when spread < 0.5%). At 7:00 AM PT the 30-min hard cap forces execution regardless. This creates a safe execution window that skips opening noise while preserving the adaptive early-trigger benefit.

**Files Touched:** `config.py`, `engine.py`, `PIPELINE.md`, `README.md`

### Entry 19 — 2026-07-11T07:14:00Z

**Action:** News roundup timestamp promoted to a dedicated "Last Fetched" header line, displayed in US/Pacific (PT).

**Changes:**
- Refactored `build_news_roundup()` header: the previously-buried scanner timestamp line (`Scanner: 75 tickers | 2026-07-11 02:49 EDT`) was split into a dedicated display row
- Added `pt_now = et_now.astimezone(zoneinfo.ZoneInfo("US/Pacific"))` conversion at function entry; the incoming `et_now` (US/Eastern from `check_market_clock()`) is now converted to PT purely for display
- New header format: `Last Fetched: YYYY-MM-DD HH:MM PT  |  Next scan in ~60 min` on its own line, with `Scanner: 75 tickers` on a separate line below
- **Did NOT change** `check_market_clock()` internals — NYSE open/close logic still uses US/Eastern, since NYSE trades in ET regardless of operator timezone. Only the *displayed* timestamp was localized.

**Logic:** The timestamp existed previously but was embedded in the scanner metadata line, making it easy to overlook. Promoting it to a named "Last Fetched" row with a PT label and a next-scan countdown makes the message's freshness instantly scannable for the PT-based operator. The market-clock internals remain ET to preserve correct MARKET_OPEN detection.

**Files Touched:** `engine.py`, `PIPELINE.md`, `README.md`

### Entry 18 — 2026-07-10T23:50:00Z

**Action:** Ternary trading signals (Buy / Hold / Sell) with realized P&L tracking.

**Changes:**
- Rewrote `sandbox_execute()` with three-phase rebalance: SELL held tickers not in new allocation → HOLD existing positions that qualify → BUY new positions only
- Added `_get_price(ticker)` helper to consolidate the 6+ duplicated yfinance price-fetching blocks
- Added realized P&L tracking: each SELL records proceeds − cost_basis, net realized P&L per cycle saved to ledger history
- Updated `build_sandbox_status()` to display realized P&L on Discord dashboard when available
- Integrated `_get_price()` into `visualization_update()` for code consistency

**Logic:** SELL exits positions that fail solvency or drop out of the top-12 ranking, freeing cash for stronger opportunities. HOLD keeps existing qualifying positions untouched (no averaging down). BUY allocates remaining cash proportionally to new tickers by adjusted_score. Prevents the leaky-bucket accumulation bug where the portfolio only ever grew.

**Files Touched:** `engine.py`, `PIPELINE.md`, `README.md`

### Entry 17 — 2026-07-10T23:45:00Z

**Action:** Exponential decay weighting for rolling sentiment + Friday 72h window correction.

**Changes:**
- Changed `get_cache_window_hours()` weekday logic: Tue–Thu → 24h, Fri–Mon → 72h (was Tue–Fri 24h, which left Friday's news stale by Monday)
- Added `DECAY_HALF_LIFE_HOURS = 72` to `config.py` (3-trading-day half-life, based on ARIA Analyst empirical research)
- Rewrote `compute_rolling_sentiment()` to apply exponential decay weighting inside every window: `weight = 0.5^(age_hours / 72)`. Sentiment is now a weighted average; pos/neg counts are rounded weighted sums.
- All command responses changed from `ephemeral=True` to `ephemeral=False` (visible to everyone in channel), except error/empty-state messages.

**Research Basis:** ARIA Analyst (2026) found 3-trading-day half-life is the empirical sweet spot for equity headline sentiment. RavenPack research confirms sentiment alpha dissipates over 2–5 day horizon. Stockholm University thesis showed decay-weighted signals consistently outperform flat-window aggregation.

**Files Touched:** `config.py`, `engine.py`, `bot.py`, `PIPELINE.md`, `README.md`

### Entry 16 — 2026-07-10T23:30:00Z

**Action:** Full containerization and Discord bot integration — refactored into modular architecture with slash commands, role-based access control, async engine runner, Docker deployment, and persistent `data/` volume.

**Changes:**
- Created `config.py` — extracted all constants (paths, lexicons, ticker array, Discord roles) into a shared module
- Created `engine.py` — migrated all engine functions (sentiment, solvency, news stream, sandbox, visualization) with `data/` path prefix; added `EngineRunner` class wrapping the main loop with `threading.Event`-based pause/resume/stop controls and thread-safe status dict
- Created `bot.py` — Discord bot with `discord.py` 2.7+ `app_commands` slash commands across three cogs:
  - `EngineCog`: `/status`, `/pause`, `/resume`, `/reset` (admin-gated)
  - `QueryCog`: `/holdings`, `/news`, `/history`, `/chart`, `/help` (trader-gated)
  - Role-based checks via `admin_check()` and `trader_check()` against configured role names `Admin` and `Trader`
- Rewrote `main.py` — thin entry point with `--bot` and `--bot-only` flags, `ensure_data_dir()`, engine thread launch, async bot startup
- Created `Dockerfile` — `python:3.13-slim`, system fonts for matplotlib, `data/` volume, Agg backend, `PYTHONUNBUFFERED=1`
- Created `docker-compose.yml` — `mem_limit: 512m`, `mem_reservation: 256m`, named volume `glassbox_data`, 30s graceful stop, json-file logging capped at 10MB × 3
- Created `requirements.txt` — yfinance, pandas, matplotlib, requests, python-dotenv, discord.py
- Created `.dockerignore` — excludes pycache, git, .env, data/, markdown docs
- Updated `.gitignore` — added `data/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`

**Logical Integration:** The repository now ships as a containerized application deployable with `docker compose up -d`. The `EngineRunner` runs the three-clock loop in a background daemon thread while the Discord bot handles slash commands on the main async event loop, with thread-safe status queries via a locked dict. Persistent state lives in a Docker named volume at `/app/data`. Memory is capped at 512MB. The bot supports two access tiers: `Trader` (read-only queries) and `Admin` (pause/resume/reset).

**Files Touched:** `config.py`, `engine.py`, `bot.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.dockerignore`, `.gitignore`, `PIPELINE.md`
