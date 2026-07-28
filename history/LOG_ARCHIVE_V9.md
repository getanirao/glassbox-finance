# Pipeline Archive V9

### Entry 33 - 2026-07-13T11:56:00Z

**Action:** Prepared Oracle Always Free ARM deployment and news-worker roles.

**Changes:**
- Reworked `Dockerfile` for multi-platform and ARM deployment with opt-in FinBERT export via `EXPORT_FINBERT=1`.
- Updated `docker-compose.yml` for Oracle Ampere defaults, persistent data, resource settings, and an optional worker profile.
- Added `--engine`, `--news-worker`, and `--news-worker-once` CLI roles in `main.py`.
- Added fetch and score-only worker operation so workers do not publish Discord dashboards or recommendations.
- Hardened the local news lock with atomic creation, owner tokens, and stale-lock cleanup.
- Added a scheduled/manual GitHub Actions news-worker workflow and setup/handoff documentation.

**Files Touched:** `Dockerfile`, `docker-compose.yml`, `.env.example`, `.github/workflows/news-worker.yml`, `config.py`, `main.py`, `engine.py`, `README.md`, `PIPELINE.md`, `ORACLE_ALWAYS_FREE_SETUP.md`, `POSTGRES_STORAGE_HANDOFF.md`
