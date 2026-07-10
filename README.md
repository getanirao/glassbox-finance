# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine that transforms blackbox buy/sell signals into auditable, semantically justified decisions.

## Current System Status

- **Live Financial Data Ingestion Active via yfinance** — `main.py` pulls raw income statements, balance sheets, and cash flow statements for any user-inputted stock ticker. Data prints cleanly to terminal for immediate inspection.
- **Data Validation Layer Online** — Invalid or delisted tickers are caught by a try/except wrapper; the system prints a specific warning and exits gracefully instead of crashing with a traceback.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and Debt-to-Equity Ratio from live balance-sheet data. Assets with CR < 1.2 or D/E > 1.5 are rejected with a full mathematical breakdown of the failure.
- **24-Hour Time Cooldown Gate Active** — A strict epoch gate limits evaluation to once per 24 hours. Early execution is blocked with a clean display of hours and minutes remaining until the next valid window.
- **Deterministic Sentiment Gate Online** — A lexicon-based engine scans yfinance news headlines and computes a Net Sentiment Score between -1.0 and +1.0. Bearish sentiment triggers a penalty multiplier that discounts the solvency health score in the final valuation.
- **Portfolio-Wide Evaluation Framework Live** — Evaluates a 10-ticker multi-sector universe (Tech, Finance, Healthcare, Consumer, Energy) through the full pipeline. Generates a ranked terminal table with solvency metrics, sentiment scores, and proportional portfolio allocation weights for all passing assets.
- **Manual System Reset Gate Available** — Running `python main.py --clear` wipes the time cooldown gate and clears active PIPELINE.md log entries while preserving the header and archive pointer, enabling a clean epoch restart.
- **Portfolio Allocation Dashboard Live** — Evaluates a 10-ticker multi-sector universe with $100,000 virtual capital. Banks bypass solvency checks via a sector exception guard. Live market prices determine integer-only share targets. Outputs a ranked 6-column terminal table: Ticker, Solvency Status, Net Sentiment Score, Allocation %, Dollar Capital, and Target Shares.
- **Semantic Analysis Engine Active** — Every solvency or sentiment rejection now includes a human-readable [Semantic Analysis] justification explaining the first-principles financial reasoning behind the mathematical gate decision.

## Features Implemented

> Phase 1 — Foundation & Instrumentation
