# Pipeline Archive V14

### 2026-07-27 20:39 (UTC)
- **Change:** Added the passive MarketWatch bridge with authenticated replay, timestamp preservation, reconciliation, and fail-closed gating.
- **Reason:** MarketWatch remains the sole execution surface while Glassbox receives durable trade context.
- **Files:** `marketwatch_sync.py`, `marketwatch-bridge/`, `engine.py`, `config.py`, `main.py`, `docker-compose.yml`, `Dockerfile`, `README.md`, `PIPELINE.md`
