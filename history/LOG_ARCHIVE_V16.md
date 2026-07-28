# Pipeline Archive V16

### 2026-07-27 21:08 (UTC)
- **Change:** Reconfigured the MarketWatch bridge for local-only operation through a token-protected loopback Docker receiver.
- **Reason:** The deployment runs on the user's PC, avoiding public ports, hosts, and cloud-account requirements.
- **Files:** `docker-compose.yml`, `.gitignore`, `.env.example`, `marketwatch-bridge.env.example`, `marketwatch-bridge/`, `README.md`, `PIPELINE.md`
