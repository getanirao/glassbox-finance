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

---

_[System Note: Archive active at `history/LOG_ARCHIVE_V1.md` | Current Archive Entries: 0]_
