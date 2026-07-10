# Pipeline Log — Wolves of Wall Street

> Active Phase: Phase 3 — Portfolio-Wide Evaluation

---

_[System Note: Archive active at `history/LOG_ARCHIVE_V1.md` | Current Archive Entries: 6]_

---

### Entry 7 — 2026-07-10T21:04:00Z

**Action:** Refactored static `RUN_MODE = "SANDBOX"` constant into CLI-based mode selection via `argparse`.

**Changes:**
- Added `import argparse` to `main.py`
- Removed global `RUN_MODE = "SANDBOX"` constant (line 24)
- Added `parse_args_and_mode()` function: uses `ArgumentParser` to handle `--sandbox` (returns `"SANDBOX"`), `--comp` (returns `"COMPETITION"`), and `--clear` (calls `handle_reset()` which now exits unconditionally)
- Removed `if "--clear" not in sys.argv: return` guard inside `handle_reset()` — reset is now invoked exclusively via `parse_args_and_mode()`
- `main()` now calls `RUN_MODE = parse_args_and_mode()` instead of `handle_reset()` at entry
- Mutually exclusive `--sandbox` / `--comp` prints error and exits
- No-argument execution prints a usage notice listing available flags, then defaults to `COMPETITION`
- Updated `README.md`:
  - Dual-mode status line references `--comp` / `--sandbox` flags
  - Terminal Execution Commands section split into four entries: Competition, Sandbox, System Reset, Default
  - `RUN_MODE` config table replaced with CLI Arguments table and Global Configuration Constants table
- Updated `PIPELINE.md` with this entry (Dual Pre-Commit Protocol)

**Files Touched:** `main.py`, `README.md`, `PIPELINE.md`
