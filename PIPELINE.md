# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

### 2026-07-10 15:58 (UTC)
- **Change:** Introduced `RUN_MODE` global flag ("COMPETITION" / "SANDBOX"); both modes share the 24-hour time gate and NYSE market clock; COMPETITION outputs manual routing table + webhook, SANDBOX auto-executes purchases, logs to `sandbox_history.json`, and renders ASCII capital growth chart via `generate_portfolio_chart()`
- **Reason:** Dual-mode architecture allowing back-test simulation (SANDBOX) without altering the competition-ready execution path (COMPETITION)
- **Files:** `main.py`, `.gitignore`

### 2026-07-10 16:30 (UTC)
- **Change:** Refactored `check_daily_gate()` to return boolean instead of `sys.exit(0)`. Added 60-minute continuous loop in `main()`. Added `send_news_flash()` for per-ticker Discord news alerts. News/sentiment runs every cycle independently of the 24h allocation gate. Allocation gate only fires during MARKET_OPEN + gate open.
- **Reason:** Phase 3 extension — continuous news streaming with detached chronology; 24h gate controls capital allocation only, news tracks every 60-minute sweep
- **Files:** `main.py`

### 2026-07-10 17:00 (UTC)
- **Change:** Added Deduplicated Rolling News Cache — persistent `.news_cache.json` stores per-headline entries (text, ticker, timestamp, pos/neg counts, net_score). `sentiment_gate()` now deduplicates against cache before scoring. `compute_rolling_sentiment()` computes 24h rolling average of per-headline net_scores per ticker. `prune_news_cache()` drops entries older than 24h each cycle. `handle_reset()` also clears `.news_cache.json`.
- **Reason:** Phase 3 enhancement — eliminates duplicate headline scoring across 60-min cycles; replaces point-in-time sentiment penalty with a rolling 24h moving average for more stable allocation decisions
- **Files:** `main.py`

### 2026-07-10 17:45 (UTC)
- **Change:** Switched `RUN_MODE` to `"SANDBOX"`. Rewrote `main()` loop with SANDBOX hyper-frequent clock (60s cycles, 24h gate bypass during MARKET_OPEN; restores 60min/24h-gate on close or COMPETITION mode). Replaced ASCII chart with matplotlib time-series in `generate_portfolio_chart()` — saves `sandbox_performance.png` (net worth vs $100k baseline). Added image attachment support to `send_webhook_payload()` — SANDBOX master report now attaches the PNG to the Discord webhook payload.
- **Reason:** Phase 3 live testing — SANDBOX mode now runs accelerated 60-second cycles with real-time matplotlib charting and image-attached Discord notifications for smartphone monitoring
- **Files:** `main.py`

### 2026-07-10 18:15 (UTC)
- **Change:** Added self-editing Discord message architecture — `load_message_state()` / `save_message_state()` / `parse_webhook_parts()` track the active dashboard message ID via `.message_state`. `send_or_update_dashboard()` POSTs the initial dashboard and saves the returned message ID; subsequent 60s cycles PATCH the same message in-place instead of creating new ones. Extracted `build_master_payload()` from `send_master_report()` for payload reuse. SANDBOX hyper mode now uses `send_or_update_dashboard()`.
- **Reason:** Phase 3 refinement — eliminates Discord channel notification spam during 1-minute sandbox loops by editing the existing dashboard message rather than posting duplicates each cycle
- **Files:** `main.py`

### 2026-07-10 18:45 (UTC)
- **Change:** Upgraded `handle_reset()` — before deleting `.message_state`, reads the stored message ID, parses the webhook URL, and sends an HTTP DELETE to `discord.com/api/webhooks/{id}/{token}/messages/{message_id}` to purge the active dashboard card from the Discord channel. Wraps the DELETE in try/except for silent error fallback. Added "GlassBox Finance: Command Reference Index" section to README.md.
- **Reason:** Phase 3 refinement — `--clear` now fully cleans up remote state (dashboard message) in addition to local state, with graceful degradation if the message was already manually deleted
- **Files:** `main.py`, `README.md`

### 2026-07-10 20:53 (UTC)
- **Change:** System clock sync — active production code freeze. All Phase 3 features locked: continuous news streaming, deduplicated rolling news cache, SANDBOX hyper-frequent 60s clock, matplotlib real-time charting, self-editing Discord dashboard, webhook image attachment, automated message purge on `--clear`.
- **Reason:** Phase 3 freeze — all core quantitative pipeline, Discord notification, and sandbox simulation features verified and stable
- **Files:** `main.py`, `README.md`, `PIPELINE.md`, `MODEL_GUIDE.md`, `.env`, `.gitignore`

---

_[System Note: Archive active at `history/LOG_ARCHIVE_V1.md` | Current Archive Entries: 6]_
