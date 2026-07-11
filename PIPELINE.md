# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

### Entry 12 — 2026-07-10T22:05:00Z

**Action:** Aligned `compute_rolling_sentiment()` window with adaptive weekend cache horizon.

**Changes:**
- Extracted weekday-based window logic into shared `get_cache_window_hours()` helper (Tue–Fri → 24, Sat–Mon → 72)
- `prune_news_cache()` now calls `get_cache_window_hours()` instead of inline weekday check
- `compute_rolling_sentiment()` now calls `get_cache_window_hours()` instead of the static `ROLLING_WINDOW_HOURS` constant
- Removed unused `ROLLING_WINDOW_HOURS = 24` constant

**Logical Integration:** Rolling sentiment averages now respect the same adaptive 72-hour window as the news cache on Sat–Mon, ensuring Friday afternoon and weekend headlines are factored into Monday morning's sentiment scores.

**Files Touched:** `main.py`, `PIPELINE.md`

---

### Entry 13 — 2026-07-10T22:15:00Z

**Action:** Added dual-window rolling sentiment architecture — short-term (adaptive 24/72h) blended with long-term (168h / 7 days).

**Changes:**
- Added constants `LONG_WINDOW_HOURS = 168` and `LONG_SENTIMENT_WEIGHT = 0.3`
- `compute_rolling_sentiment()` accepts optional `window_hours` parameter (defaults to `get_cache_window_hours()` if None)
- `sentiment_gate()` now computes both short-term and long-term rolling sentiment, blends them for penalty calculation: `blended = 0.7 × short + 0.3 × long`
- Return value expanded from 6 to 10 fields (adds `long_sent`, `long_pos`, `long_neg`, `long_count`)
- `process_ticker()` unpacks all 10 fields and stores long metrics in result dict under `long_sentiment`, `long_rolling_pos`, `long_rolling_neg`, `long_rolling_count`
- `summarize_news_entry()` accepts optional `long_sent` param; dual format: `TICKER [short / long] (X P / Y N) -> headline`
- `build_news_roundup()` passes `r.get("long_sentiment")` to `summarize_news_entry()`
- Console print updated to show short, 7d, and blended scores during news caching

**Files Touched:** `main.py`, `README.md`, `PIPELINE.md`

---

### Entry 14 — 2026-07-10T22:30:00Z

**Action:** Deployed 75-ticker watchlist scanner with top-12 portfolio concentration filter and under-subscription safeguard.

**Changes:**
- Added constants `WATCHLIST_SCANNER_LIMIT = 75` and `MAX_PORTFOLIO_HOLDINGS = 12`
- Replaced static 10-ticker universe with a 75-ticker broad-market array across 7 sectors: Technology (14), Healthcare (12), Energy (10), Consumer Cyclical (12), Industrials (12), Utilities (10), Finance (5)
- Expanded `INSTITUTIONAL_BANKS` to `{"JPM", "GS", "BAC", "MS", "C"}` for bank exemption guards
- `display_portfolio_table()` now clips ranked results to top `MAX_PORTFOLIO_HOLDINGS` and displays scanner telemetry (75 evaluated, N passed, top M funded)
- `build_master_payload()` same clipping; shows "Scanner: 75 tickers | Passed: N | Funded: M"
- `build_sandbox_status()` shows `Scanner: 75 tickers | Holdings: X / 12`
- `build_news_roundup()` header shows scanner count and timestamp inline
- `main()` COMPETITION branch clips `passed_results` to top `MAX_PORTFOLIO_HOLDINGS` before display and report
- `main()` SANDBOX OBSERVING branch same clipping before `sandbox_execute` and dashboard
- Under-subscription safeguard: capital denominator uses `min(MAX_PORTFOLIO_HOLDINGS, len(passing))` via slicing
- Rate-limit protection preserved: `process_ticker` (accounting + news) only runs on 24h cycle, not 1-min visualization loop
- Banner updated: `Mode: SANDBOX | Watchlist: 75 tickers | Max Holdings: 12`

**Files Touched:** `main.py`, `README.md`, `PIPELINE.md`
