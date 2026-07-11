# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine that transforms blackbox buy/sell signals into auditable, semantically justified decisions.

## Current System Status

- **Live Financial Data Ingestion Active via yfinance** — `main.py` pulls raw income statements, balance sheets, and cash flow statements for any user-inputted stock ticker. Data prints cleanly to terminal for immediate inspection.
- **Data Validation Layer Online** — Invalid or delisted tickers are caught by a try/except wrapper; the system prints a specific warning and exits gracefully instead of crashing with a traceback.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and Debt-to-Equity Ratio from live balance-sheet data. Assets with CR < 1.2 or D/E > 1.5 are rejected with a full mathematical breakdown of the failure.
- **24-Hour Time Cooldown Gate Active** — A strict epoch gate limits evaluation to once per 24 hours. Early execution is blocked with a clean display of hours and minutes remaining until the next valid window.
- **Deterministic Sentiment Gate Online** — A lexicon-based engine scans yfinance news headlines and computes a Net Sentiment Score between -1.0 and +1.0. Bearish sentiment triggers a penalty multiplier that discounts the solvency health score in the final valuation.
- **75-Ticker Watchlist Scanner Active** — Engine maintains a broad-market universe of 75 liquid U.S. equities across 7 sectors (Technology, Healthcare, Energy, Consumer Cyclical, Industrials, Utilities, Finance). Every 24-hour cycle, all 75 tickers pass through solvency screening and dual-horizon sentiment scoring. The top 12 passing assets are funded with proportional capital allocation, with an under-subscription safeguard that dynamically scales the denominator when fewer than 12 pass.
- **Manual System Reset Gate Available** — Running `python main.py --clear` wipes the time cooldown gate, clears the news cache, resets the observation state, purges the active Discord dashboard message from channel history, deletes the local message state tracker, and resets PIPELINE.md log entries while preserving the header and archive pointer, enabling a clean epoch restart.
- **Ternary Trading Signals (Buy / Hold / Sell) Active** — Each rebalance cycle executes a three-phase portfolio sweep: **SELL** exits held positions that fail solvency or drop out of the top 12 (freeing cash, recording realized P&L), **HOLD** keeps qualifying existing positions untouched, and **BUY** allocates remaining cash proportionally by adjusted_score to new tickers only. Prevents the leaky-bucket accumulation pattern and enables realistic competition portfolio management.
- **Semantic Analysis Engine Active** — Every solvency or sentiment rejection now includes a human-readable [Semantic Analysis] justification explaining the first-principles financial reasoning behind the mathematical gate decision.
- **NYSE Market Clock Gate Active** — Detects US Eastern Time. In COMPETITION mode, it restricts executable allocation orders to regular market hours (9:30 AM–4:00 PM ET, Mon–Fri). In SANDBOX mode, it now **prevents simulated BUY/SELL/HOLD trades** during off-market hours, while still computing all analytics.
- **Automated Team Desk Notifications Online** — News Roundups are now transmitted to Discord 24/7. Dashboard messages are updated dynamically, with robust error handling for stale message IDs, automatically posting new messages if needed. Portfolio reports for MARKET_OPEN runs are transmitted as before; off-hours runs suppress these specific alerts.
- **Dual-Mode Operating System Active** — Select mode at launch with `python main.py --comp` (manual routing table + webhook alerts) or `python main.py --sandbox` (auto-execution with persistent portfolio ledger, real-time matplotlib charting, and twin-clock architecture). Both modes enforce the 24-hour cooldown and NYSE market clock. Running with no arguments defaults to COMPETITION.
- **Continuous 60-Minute News Stream Active** — A dedicated news clock runs independently of market hours, scraping headlines for all 75 tickers every 60 minutes. Between ticker fetches, calls are jittered with 1.5–3.5s random sleep to avoid Yahoo Finance rate limits. A file-based lock (`.news_lock`) prevents race conditions between the news stream and the 24-hour decision clock. Each stream cycle compiles a single batched **News Roundup** Discord message (POST on first, PATCH on subsequent) with a `Last Fetched: HH:MM PT` freshness header. Payloads are hard-capped under Discord's 2000-char limit with suffix-aware truncation, and PATCH errors are differentiated — only HTTP 404 (genuinely deleted message) clears the message ID, preventing duplicate roundup messages on transient errors. The 24-hour decision clock reads sentiment exclusively from `.news_cache.json` — never calling `stock.news` — eliminating redundant API traffic.
- **Deduplicated Rolling News Cache Active** — A persistent `.news_cache.json` stores every unique headline with per-article sentiment scores. Duplicate headlines across 60-minute cycles are silently skipped.
- **Decay-Weighted Rolling Sentiment Architecture Online** — Two independent sentiment horizons govern each ticker's penalty multiplier. The **short-term** score uses an adaptive window (24h Tue–Thu / 72h Fri–Mon) for reactive headline response. The **long-term** score uses a fixed 168-hour (7-day) window as a trend anchor. Both windows apply **exponential decay weighting** with a 72-hour half-life (`weight = 0.5^(age_hours / 72)`), so newer headlines contribute more than older ones within each window. The blended penalty (`0.7 × short + 0.3 × long`) smooths noise while preserving real-time market sensitivity. The news roundup displays both scores side-by-side.
- **Adaptive Weekend Cache Horizon Online** — The `prune_news_cache()` gate automatically adjusts its expiration window based on the UTC weekday. Tuesday through Thursday uses a strict 24-hour cache window. Friday through Monday dynamically extends to 72 hours, preserving Friday afternoon and weekend corporate news for Monday morning's rolling sentiment averages.
- **Twin-Clock Architecture Active** — Two independent clocks govern the engine. The **24-Hour Decision Clock** restricts core portfolio re-allocations (solvency checks, sentiment re-parsing, holdings changes) to once per day in both COMPETITION and SANDBOX modes. The **1-Minute Visualization Clock** in SANDBOX mode runs continuous 60-second cycles that pull only current spot prices, calculate live net worth, update the portfolio history ledger, and re-plot the matplotlib performance chart — without ever changing holdings.
- **Smart Execution Trigger Online** — When the 24-hour decision gate expires, the engine enters an **Observation State** instead of immediately executing. It monitors the 5-minute rolling volatility spread across the full 75-ticker watchlist. The daily rebalance fires only when volatility drops below a 0.5% threshold — but never within the first 10 minutes of market open (warm-up floor), and no later than 30 minutes (hard cap). This avoids the chaotic opening price-discovery window while still catching early stabilization. A distinct `[Smart Trigger]` console log marks the execution.
- **Self-Editing Discord Dashboard Active** — The dashboard displays the live clock state (`LOCKED`, `OBSERVING INTRA-DAY VOLATILITY`, or `UPDATING REAL-TIME VALUE`) and the current **market state** (e.g., `MARKET_OPEN`, `ANALYTICAL_OFF_HOURS`) alongside the changing line chart. The first cycle POSTs a new message; all subsequent 1-minute cycles PATCH the same message in-place with updated text and chart attachment. Robust error handling is now in place for `404 Not Found` errors, clearing stale message IDs and automatically posting a new dashboard message if the old one is deleted from Discord. Historical chart stacking is prevented by injecting an explicit empty `attachments` array into the `payload_json` envelope before each PATCH, ensuring Discord removes the prior image before uploading the new one.
- **Automated Discord Message Purge on Reset** — Running `python main.py --clear` sends HTTP DELETE requests to Discord to remove both the active dashboard message (from `.message_state`) and the news roundup message (from `.news_message_state`) from channel history before cleaning up local state. If a message was already deleted, logs a warning and continues without crashing.

## GlassBox Finance: Command Reference Index

A complete operational directory detailing all valid terminal arguments, system configuration parameters, and dashboard modes for our quantitative research suite.

### Terminal Execution Commands

#### Competition Advisory Desk (Default)
Executes with strict 24-hour time locks and NYSE hour boundaries. Outputs text-only integer share ledgers for manual tournament order entries.
```bash
python main.py --comp
```

#### Sandbox Paper Trading
Accelerates to a high-speed 1-minute visualization cadence. Automates virtual data collection, generates matplotlib real-time performance charts, and streams live graphical dashboard updates. **Automated BUY/SELL/HOLD trades only occur during NYSE market open hours.**
```bash
python main.py --sandbox
```

#### System Reset & Infrastructure Purge
Deletes local time tracking parameters (`.last_run`), wipes active news caches (`.news_cache.json`), purges your live dashboard card from the Discord channel history, and resets local message tracking states (`.message_state`).
```bash
python main.py --clear
```

#### Default (No Arguments)
If no flag is provided, the engine defaults to COMPETITION mode and prints a notice listing the available command choices.
```bash
python main.py
```

---

### Command-Line Arguments
*Parsed at launch via `argparse` in `parse_args_and_mode()`.*

| Argument | Mode | Operational Outcome |
| :--- | :--- | :--- |
| **`--comp`** | COMPETITION | Enforces strict 24-hour time locks and NYSE hour boundaries. Outputs text-only integer share ledgers designed for manual tournament order entries. |
| **`--sandbox`** | SANDBOX | Accelerates the execution loop to a high-speed 1-minute cadence. Automates virtual data collection, generates `matplotlib` visual trend charts, and streams live graphical updates. **Automated BUY/SELL/HOLD trades only occur during NYSE market open hours.** |
| **`--clear`** | — | Purges all local state (`.last_run`, `.news_cache.json`, `.observation_state`, `.message_state`), deletes the active Discord dashboard message, and resets PIPELINE.md log entries. |
| **`--bot`** | Both | Starts Discord bot alongside engine with slash commands. |
| **`--bot-only`** | — | Starts only the Discord bot without the engine. Requires `BOT_TOKEN` env. |
| *(none)* | COMPETITION | Default mode. Prints a usage notice then runs as COMPETITION. |

### Docker Commands
| Command | Description |
| :--- | :--- |
| `docker compose up -d` | Build and start container in background |
| `docker compose logs -f` | Follow engine + bot logs |
| `docker compose down` | Stop container gracefully |
| `docker compose exec glassbox python main.py --clear` | Reset state from inside container |

### Global Configuration Constants
*Located in `config.py` for framework calibration.*

| Constant | Default | Purpose |
| :--- | :--- | :--- |
| **`STARTING_CAPITAL`** | `100000` | Anchors the allocation engine's cash base to match the official bounds of the target competition simulator. |
| **`GATE_HOURS`** | `24` | Cooldown period between daily allocation cycles. |
| **`VOLATILITY_THRESHOLD`** | `0.005` | Maximum 5-minute rolling volatility spread (0.5%) for smart trigger execution. |
| **`VOLATILITY_WINDOW`** | `5` | Number of 1-minute price samples used for rolling volatility computation. |
| **`GRACE_MINUTES`** | `30` | Market-open hard cap: forces execution after this many minutes regardless of volatility. |
| **`WARMUP_MINUTES`** | `10` | Market-open warm-up floor: no execution allowed before this many minutes, regardless of how calm volatility appears. |
| **`WATCHLIST_SCANNER_LIMIT`** | `75` | Number of equities in the broad-market watchlist universe. |
| **`MAX_PORTFOLIO_HOLDINGS`** | `12` | Maximum funded portfolio positions per allocation cycle. |
| **`LONG_WINDOW_HOURS`** | `168` | Long-term sentiment trend anchor window (7 days). |
| **`LONG_SENTIMENT_WEIGHT`** | `0.3` | Blending weight for long-term sentiment in penalty calculation. |
| **`NEWS_CYCLE_HOURS`** | `1` | Frequency of the continuous news stream (hours). |
| **`NEWS_RATE_MIN`** | `1.5` | Minimum jitter sleep (seconds) between ticker fetches in the news stream. |
| **`NEWS_RATE_MAX`** | `3.5` | Maximum jitter sleep (seconds) between ticker fetches in the news stream. |
| **`DECAY_HALF_LIFE_HOURS`** | `72` | Half-life for exponential sentiment decay weighting (3 trading days). |

### Automated Time-Series Status Flags
*Dynamically calculated by the engine's internal clock layers.*

- **`MARKET_OPEN`**: Active during regular NYSE trading hours (9:30 AM – 4:00 PM Eastern, Monday through Friday). Unlocks full portfolio allocation ledgers and transaction share routing tables.
- **`ANALYTICAL_OFF_HOURS`**: Active outside regular market hours and weekends. Enforces an asset allocation lock to protect capital from extended-hours liquidity traps, shifting the engine into a continuous data and text sentiment screening stream.

### Three-Clock Architecture

Three independent clocks govern the engine in a single-threaded pipeline. The **60-Minute News Stream** scrapes Yahoo Finance headlines for all 75 tickers every hour (24/7/365), independently of market hours, with jittered rate limiting between requests. The **24-Hour Decision Clock** restricts core portfolio re-allocations (solvency checks, sentiment re-parsing, holdings changes) to once per day in both COMPETITION and SANDBOX modes. The **1-Minute Visualization Clock** in SANDBOX mode runs continuous 60-second cycles that pull only current spot prices, calculate live net worth, update the portfolio history ledger, and re-plot the matplotlib performance chart — without ever changing holdings.

#### Observation State Machine
*Persisted in `.observation_state` and displayed on the live Discord dashboard.*

- **`LOCKED`**: 24-hour decision gate is active. Rebalance completed. Visualization-only 1-minute cycles update net worth and chart without changing holdings.
- **`OBSERVING INTRA-DAY VOLATILITY`**: 24-hour gate has expired. Engine is collecting 1-minute spot prices and monitoring the 5-minute rolling volatility spread across all tickers. No trades execute until the spread drops below 0.5% or the 30-minute market-open grace period elapses.
- **`UPDATING REAL-TIME VALUE`**: Post-rebalance state. Holdings are locked for 24 hours. Dashboard refreshes every 60 seconds with current spot prices, portfolio net worth, and the updated performance chart.

### Discord Bot (Slash Commands)

The engine can run alongside a Discord application bot that responds to slash commands in your server.

| Command | Description |
| :--- | :--- |
| `/status` | Engine mode, clock state, portfolio value, last run |
| `/holdings` | Current portfolio positions with live prices |
| `/news` | News cache summary with short + 7d sentiment |
| `/history` | Last 20 portfolio value entries with change |
| `/chart` | Latest `sandbox_performance.png` |
| `/help` | Command list |
| `/pause` | Pause the engine loop |
| `/resume` | Resume the engine loop |
| `/stop` | Gracefully stop engine (preserves cache) |
| `/clear` | Clear news cache and state files |
| `/run_sandbox` | Trigger immediate SANDBOX evaluation cycle |
| `/run_comp` | Trigger immediate COMPETITION evaluation cycle |

Role-checking is disabled — all commands available to everyone.

### Docker Deployment

```bash
# Set secrets
export BOT_TOKEN="your_discord_bot_token"
export WEBHOOK_URL="https://discord.com/api/webhooks/..."

# Set mode (defaults to SANDBOX if unset)
#   SANDBOX     — Paper trading with per-minute chart, auto-execute buy/sell/hold
#   COMPETITION — Manual advisory desk, outputs trade recommendations
export RUN_MODE=SANDBOX

# Build and start
docker compose up -d

# View logs
docker compose logs -f --tail 100

# Stop
docker compose down
```

Configuration via `docker-compose.yml`: 512MB memory limit, named volume `glassbox_data` for persistent state, auto-restart on failure, run mode driven by `RUN_MODE` env var (no rebuild needed to switch).

## Features Implemented

> Phase 1 — Foundation & Instrumentation
