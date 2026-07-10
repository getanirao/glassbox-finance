# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

### 2026-07-10 06:50 (UTC)
- **Change:** Added `handle_reset()` — `--clear` argument deletes `.last_run`, wipes PIPELINE.md log entries while preserving header, phase label, and archive pointer
- **Reason:** Phase 3 maintenance — allows manual epoch reset without manual file editing; preserves archive integrity
- **Files:** `main.py`

### 2026-07-10 07:10 (UTC)
- **Change:** Refactored entire Phase 3 framework: added `STARTING_CAPITAL=100000`, sector exception guard for JPM/GS with baseline neutral score (75.0), live price fractional-order protection via `int()`, and 6-column portfolio dashboard
- **Reason:** Phase 3 completion — mirrors competition simulator dollar metrics with bank-book exception handling and real-time price-based share allocation
- **Files:** `main.py`

### 2026-07-10 07:20 (UTC)
- **Change:** Integrated native [Semantic Analysis] explanations for D/E failures, Current Ratio failures, and negative Sentiment Gate results in `process_ticker()`
- **Reason:** Glassbox transparency mandate — each gate rejection now surfaces a human-readable, first-principles justification for the mathematical decision
- **Files:** `main.py`

### 2026-07-10 15:20 (UTC)
- **Change:** Added `check_market_clock()` — detects US Eastern Time weekday market hours (9:30 AM–4:00 PM); MARKET_OPEN shows full trade execution table, ANALYTICAL_OFF_HOURS prints summary with processed/passed counts and top performer
- **Reason:** Prevent off-hours trade signal output; analytics still run for research while blocking premature execution routing
- **Files:** `main.py`

### 2026-07-10 15:22 (UTC)
- **Change:** Added `post_to_team_desk()` — parses leaderboard into formatted text and sends HTTP POST to Discord/Slack webhook loaded from `WEBHOOK_URL` env var; fires only during MARKET_OPEN
- **Reason:** Automated team notification for every valid trading run; webhook URL kept out of source code via .env
- **Files:** `main.py`, `.env`

---

_[System Note: Archive active at `history/LOG_ARCHIVE_V1.md` | Current Archive Entries: 0]_
