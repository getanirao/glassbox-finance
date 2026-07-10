# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine that transforms blackbox buy/sell signals into auditable, semantically justified decisions.

## Current System Status

- **Live Financial Data Ingestion Active via yfinance** — `main.py` pulls raw income statements, balance sheets, and cash flow statements for any user-inputted stock ticker. Data prints cleanly to terminal for immediate inspection.
- **Data Validation Layer Online** — Invalid or delisted tickers are caught by a try/except wrapper; the system prints a specific warning and exits gracefully instead of crashing with a traceback.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and Debt-to-Equity Ratio from live balance-sheet data. Assets with CR < 1.2 or D/E > 1.5 are rejected with a full mathematical breakdown of the failure.
- **24-Hour Time Cooldown Gate Active** — A strict epoch gate limits evaluation to once per 24 hours. Early execution is blocked with a clean display of hours and minutes remaining until the next valid window.
- **Deterministic Sentiment Gate Online** — A lexicon-based engine scans yfinance news headlines and computes a Net Sentiment Score between -1.0 and +1.0. Bearish sentiment triggers a penalty multiplier that discounts the solvency health score in the final valuation.

## Features Implemented

> Phase 1 — Foundation & Instrumentation
