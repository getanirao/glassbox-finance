# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

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
