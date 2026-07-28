# Pipeline Archive V15

### 2026-07-27 20:46 (UTC)
- **Change:** Allowed baseline establishment when the ledger has only cash-only visualization history, while preserving a hard block for prior trades.
- **Reason:** Chart telemetry must not require a destructive reset before the first actual trade.
- **Files:** `marketwatch_sync.py`, `README.md`, `PIPELINE.md`
