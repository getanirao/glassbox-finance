# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine that transforms blackbox buy/sell signals into auditable, semantically justified decisions.

## Current System Status

- **Live Financial Data Ingestion Active via yfinance** — `main.py` pulls raw income statements, balance sheets, and cash flow statements for any user-inputted stock ticker. Data prints cleanly to terminal for immediate inspection.
- **Data Validation Layer Online** — Invalid or delisted tickers are caught by a try/except wrapper; the system prints a specific warning and exits gracefully instead of crashing with a traceback.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and Debt-to-Equity Ratio from live balance-sheet data. Assets with CR < 1.2 or D/E > 1.5 are rejected with a full mathematical breakdown of the failure.
- **24-Hour Time Cooldown Gate Active** — A strict epoch gate limits evaluation to once per 24 hours. Early execution is blocked with a clean display of hours and minutes remaining until the next valid window.
- **Deterministic Sentiment Gate Online** — A lexicon-based engine scans yfinance news headlines and computes a Net Sentiment Score between -1.0 and +1.0. Bearish sentiment triggers a penalty multiplier that discounts the solvency health score in the final valuation.
- **Portfolio-Wide Evaluation Framework Live** — Evaluates a 10-ticker multi-sector universe (Tech, Finance, Healthcare, Consumer, Energy) through the full pipeline. Generates a ranked terminal table with solvency metrics, sentiment scores, and proportional portfolio allocation weights for all passing assets.
- **Manual System Reset Gate Available** — Running `python main.py --clear` wipes the time cooldown gate, clears the news cache, resets the observation state, purges the active Discord dashboard message from channel history, deletes the local message state tracker, and resets PIPELINE.md log entries while preserving the header and archive pointer, enabling a clean epoch restart.
- **Portfolio Allocation Dashboard Live** — Evaluates a 10-ticker multi-sector universe with $100,000 virtual capital. Banks bypass solvency checks via a sector exception guard. Live market prices determine integer-only share targets. Outputs a ranked 6-column terminal table: Ticker, Solvency Status, Net Sentiment Score, Allocation %, Dollar Capital, and Target Shares.
- **Semantic Analysis Engine Active** — Every solvency or sentiment rejection now includes a human-readable [Semantic Analysis] justification explaining the first-principles financial reasoning behind the mathematical gate decision.
- **NYSE Market Clock Gate Active** — Detects US Eastern Time and only displays the full trade execution dashboard during regular market hours (9:30 AM–4:00 PM ET, Mon–Fri). Off-hours runs still compute all analytics but output a summary report instead of executable allocation orders.
- **Automated Team Desk Notifications Online** — Every valid MARKET_OPEN run transmits a formatted portfolio report to a Discord/Slack webhook loaded securely from the `.env` file. Off-hours runs suppress the alert.
- **Dual-Mode Operating System Active** — Select mode at launch with `python main.py --comp` (manual routing table + webhook alerts) or `python main.py --sandbox` (auto-execution with persistent portfolio ledger, real-time matplotlib charting, and twin-clock architecture). Both modes enforce the 24-hour cooldown and NYSE market clock. Running with no arguments defaults to COMPETITION.
- **Continuous News Streaming Framework Online** — Engine runs an infinite 60-minute loop across the full 10-ticker universe. Every cycle fetches live data, evaluates solvency, scans news sentiment, and transmits per-ticker Discord news alerts. The 24-hour allocation gate is detached from news — capital distribution fires only when NYSE is open AND 24h cooldown has expired.
- **Deduplicated Rolling News Cache Active** — A persistent `.news_cache.json` stores every unique headline with per-article sentiment scores. Duplicate headlines across 60-minute cycles are silently skipped. The sentiment multiplier now uses a 24-hour rolling moving average of all unique headlines per ticker, replacing the previous point-in-time scoring for more stable and representative penalty calculations.
- **Twin-Clock Architecture Active** — Two independent clocks govern the engine. The **24-Hour Decision Clock** restricts core portfolio re-allocations (solvency checks, sentiment re-parsing, holdings changes) to once per day in both COMPETITION and SANDBOX modes. The **1-Minute Visualization Clock** in SANDBOX mode runs continuous 60-second cycles that pull only current spot prices, calculate live net worth, update the portfolio history ledger, and re-plot the matplotlib performance chart — without ever changing holdings.
- **Smart Execution Trigger Online** — When the 24-hour decision gate expires, the engine enters an **Observation State** instead of immediately executing. It monitors the 5-minute rolling volatility spread across the full 10-ticker universe. The daily rebalance fires only when volatility drops below a 0.5% threshold or after a 30-minute market-open grace period, protecting against intra-day whipsaw risk. A distinct `[Smart Trigger]` console log marks the execution.
- **Self-Editing Discord Dashboard Active** — The dashboard displays the live clock state (`LOCKED`, `OBSERVING INTRA-DAY VOLATILITY`, or `UPDATING REAL-TIME VALUE`) alongside the changing line chart. The first cycle POSTs a new message; all subsequent 1-minute cycles PATCH the same message in-place with updated text and chart attachment.
- **Automated Discord Message Purge on Reset** — Running `python main.py --clear` sends an HTTP DELETE to Discord to remove the active dashboard message from channel history before cleaning up local state. If the message was already deleted, logs a warning and continues without crashing.

## GlassBox Finance: Command Reference Index

A complete operational directory detailing all valid terminal arguments, system configuration parameters, and dashboard modes for our quantitative research suite.

### Terminal Execution Commands

#### Competition Advisory Desk (Default)
Executes with strict 24-hour time locks and NYSE hour boundaries. Outputs text-only integer share ledgers for manual tournament order entries.
```bash
python main.py --comp
```

#### Sandbox Paper Trading
Accelerates to a high-speed 1-minute visualization cadence during market open hours. Automates virtual data collection, generates matplotlib real-time performance charts, and streams live graphical dashboard updates.
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
| **`--sandbox`** | SANDBOX | Accelerates the execution loop to a high-speed 1-minute cadence during market open hours. Automates virtual data collection, generates `matplotlib` visual trend charts, and streams live graphical updates. |
| **`--clear`** | — | Purges all local state (`.last_run`, `.news_cache.json`, `.observation_state`, `.message_state`), deletes the active Discord dashboard message, and resets PIPELINE.md log entries. |
| *(none)* | COMPETITION | Default mode. Prints a usage notice then runs as COMPETITION. |

### Global Configuration Constants
*Located at the top of `main.py` for framework calibration.*

| Constant | Default | Purpose |
| :--- | :--- | :--- |
| **`STARTING_CAPITAL`** | `100000` | Anchors the allocation engine's cash base to match the official bounds of the target competition simulator. |
| **`GATE_HOURS`** | `24` | Cooldown period between daily allocation cycles. |
| **`VOLATILITY_THRESHOLD`** | `0.005` | Maximum 5-minute rolling volatility spread (0.5%) for smart trigger execution. |
| **`VOLATILITY_WINDOW`** | `5` | Number of 1-minute price samples used for rolling volatility computation. |
| **`GRACE_MINUTES`** | `30` | Market-open grace period before forced execution regardless of volatility. |

### Automated Time-Series Status Flags
*Dynamically calculated by the engine's internal clock layers.*

- **`MARKET_OPEN`**: Active during regular NYSE trading hours (9:30 AM – 4:00 PM Eastern, Monday through Friday). Unlocks full portfolio allocation ledgers and transaction share routing tables.
- **`ANALYTICAL_OFF_HOURS`**: Active outside regular market hours and weekends. Enforces an asset allocation lock to protect capital from extended-hours liquidity traps, shifting the engine into a continuous data and text sentiment screening stream.

### Twin-Clock Observation State Machine
*Persisted in `.observation_state` and displayed on the live Discord dashboard.*

- **`LOCKED`**: 24-hour decision gate is active. Rebalance completed. Visualization-only 1-minute cycles update net worth and chart without changing holdings.
- **`OBSERVING INTRA-DAY VOLATILITY`**: 24-hour gate has expired. Engine is collecting 1-minute spot prices and monitoring the 5-minute rolling volatility spread across all tickers. No trades execute until the spread drops below 0.5% or the 30-minute market-open grace period elapses.
- **`UPDATING REAL-TIME VALUE`**: Post-rebalance state. Holdings are locked for 24 hours. Dashboard refreshes every 60 seconds with current spot prices, portfolio net worth, and the updated performance chart.

## Features Implemented

> Phase 1 — Foundation & Instrumentation
