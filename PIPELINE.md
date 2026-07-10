# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

### Entry 11 — 2026-07-10T21:40:00Z

**Action:** Replaced 10 individual per-ticker `send_news_flash()` calls with a unified batched `send_batched_news()` roundup message.

**Changes:**
- Added `NEWS_MESSAGE_STATE_FILE = ".news_message_state"` constant
- Added `load_news_message_state()` / `save_news_message_state()` helpers for roundup message ID persistence
- Implemented `summarize_news_entry()` — scans each ticker's incoming headlines, selects the one with highest absolute net sentiment via lexicon scoring, truncates at a clean word boundary near 130 chars, returns formatted row: `TICKER [+X.XX] (X P / Y N) -> Truncated headline…`
- Implemented `build_news_roundup()` — compiles all 10 rows into a single markdown card with `====` borders, timestamp, and 24h window status
- Implemented `send_batched_news()` — transmits roundup via Discord webhook (POST on first cycle with `?wait=true`, saves ID to `.news_message_state`; PATCH on subsequent cycles to edit in-place)
- Updated `handle_reset()` — reads `.news_message_state`, fires HTTP DELETE to purge the historical roundup card, deletes the tracker file; prints `.news_message_state` status in the reset banner
- Replaced `for r in news_alerts: send_news_flash(r)` in both COMPETITION and SANDBOX OBSERVING branches with single `send_batched_news(news_alerts, et_now)` call after the 10-ticker loop
- Kept `send_news_flash()` defined but no longer called from `main()`

**Files Touched:** `main.py`, `README.md`, `PIPELINE.md`
