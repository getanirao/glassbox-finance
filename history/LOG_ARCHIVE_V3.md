# Log Archive V3

Archived entries from `PIPELINE.md` (batch 2026-07-12). This file is static.

---

### Entry 27 - 2026-07-12T09:00:00Z

**Action:** Moved to a competition-only architecture with persistent competition ledger, dashboard, trade logging, and market-gated final recommendations.

**Changes:** Removed sandbox/observation execution paths; added competition ledger and dashboard state; added `/trade` and `/hold`; unified the 60-minute news evaluation with the 60-second visualization loop; defined institutional-bank handling and updated reset state cleanup.

**Files Touched:** `config.py`, `engine.py`, `bot.py`, `PIPELINE.md`, `README.md`

---

### Entry 26 - 2026-07-12T08:35:00Z

**Action:** Replaced the small hardcoded lexicons with the Loughran-McDonald financial dictionary and retained a reproducible generation script.

**Changes:** Added generated `lexicon.py`, moved lexicon imports into `config.py`, updated the container image, and preserved `gen_lexicon.py` for reproducibility.

**Files Touched:** `lexicon.py`, `config.py`, `Dockerfile`, `gen_lexicon.py`, `PIPELINE.md`, `README.md`
