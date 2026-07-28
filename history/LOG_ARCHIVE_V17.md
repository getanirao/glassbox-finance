# Pipeline Archive V17

### 2026-07-27 22:02 (UTC)
- **Change:** Replaced the forced top-12 allocation with a six-core/eight-maximum conviction portfolio, up to eight eligible buys per cycle, sector and growth/AI factor caps, persistent reserve-slot criteria, and reason-coded scorecard decisions.
- **Reason:** A short ranking competition should avoid weak positive signals and correlated concentration without mechanically filling every slot or forcing churn in current holdings.
- **Files:** `config.py`, `engine.py`, `README.md`, `history/LOG_ARCHIVE_V10.md`, `PIPELINE.md`

---

### 2026-07-27 21:56 (UTC)
- **Change:** Replaced unchanged-snapshot suppression with a one-minute authenticated Portfolio heartbeat and return the receiver's current status to the in-page badge.
- **Reason:** Stable-payload deduplication stopped all receiver calls after baseline and let the five-minute safety clock become stale without a trade or page failure.
- **Files:** `marketwatch-bridge/service-worker.js`, `marketwatch-bridge/manifest.json`, `marketwatch-bridge/README.md`, `README.md`, `history/LOG_ARCHIVE_V9.md`, `PIPELINE.md`

---

### 2026-07-27 21:46 (UTC)
- **Change:** Removed Discord trade, bulk-trade, and hold mutation commands; dashboard instructions now direct final orders to MarketWatch and `/status` surfaces bridge health.
- **Reason:** MarketWatch is the sole execution source once the passive bridge is healthy. A second Discord ledger-entry path could duplicate fills or destroy timestamped trade context.
- **Files:** `bot.py`, `engine.py`, `README.md`, `history/LOG_ARCHIVE_V8.md`, `PIPELINE.md`

---

### 2026-07-27 21:17 (UTC)
- **Change:** Added a clickable extension status popup and recognized the visible no-holdings state as a complete empty Portfolio snapshot.
- **Reason:** A cash-only Portfolio must establish a baseline without a test trade.
- **Files:** `marketwatch-bridge/manifest.json`, `marketwatch-bridge/content.js`, `marketwatch-bridge/popup.html`, `marketwatch-bridge/popup.js`, `README.md`, `history/LOG_ARCHIVE_V7.md`, `PIPELINE.md`
