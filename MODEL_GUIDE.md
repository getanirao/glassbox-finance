# Model Guide — Wolves of Wall Street

## Purpose
This document governs how all AI agents (including opencode) interact with the project. Every change, decision, or suggestion made by any model **must** be logged.

## Dual Pre-Commit Protocol
Right before concluding a major task and preparing for a commit, you MUST update **both** files **simultaneously** — they serve different masters and are not interchangeable.

### 1. Update `PIPELINE.md` (Internal Machine Log)
- Append a **technical, timestamped, raw log entry** for AI agents to track changes line-by-line.
- Use this exact format:
  ```markdown
  ### YYYY-MM-DD HH:MM (UTC)
  - **Change:** <what was done>
  - **Reason:** <why it was done>
  - **Files:** <file paths affected>
  ```

### 2. Update `README.md` (Public Human Dashboard)
- Update the "Current System Status" or "Features Implemented" section with a **high-level, clean, professional bullet point**.
- Written for **human judges**, not AI. Highlight what quantitative features are live (e.g., "Live Data Scraping Active via yfinance").
- Be concise and judge-friendly — no raw timestamps or internal reasoning.

## PIPELINE.md — Lean & Focused
`PIPELINE.md` must stay small to keep model response times fast:
- Keep only **1 active phase header** (e.g. `Phase 1 — Foundation`)
- Keep only the **last 5–10 log entries**
- When entries exceed 10, **cut the oldest batch** and move them to `/history/LOG_ARCHIVE_V<n>.md`
- Increment the archive version number each time (V1 → V2 → V3 …)
- **Always leave a pointer line** at the bottom of `PIPELINE.md`:
  ```
  _Older logs archived in /history/LOG_ARCHIVE_V1.md_
  ```

## API Key Safety
- **Never** hardcode API keys in source code.
- Always load secrets from environment variables via `os.environ` or `python-dotenv`.
- A `.env` file exists in the project root (see `.gitignore` — it is excluded from version control).
- Reference keys like `os.getenv("ALPHA_VANTAGE_KEY")` or `os.getenv("FINANCIAL_MODELING_PREP_KEY")`.

## Reversion Directive
If a code modification results in a runtime error that cannot be resolved in two consecutive prompt iterations, you must:
1. Halt execution immediately.
2. State the exact error log to the user.
3. Prompt the user to revert to the last stable Git commit before attempting an alternative structural approach.

## Glassbox Principle
The goal is **glassbox transparency**: every blackbox decision must be surfaced, documented, and justified so it can be audited by another model or human.
