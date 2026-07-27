# Oracle Always Free VPS Setup

This repo is prepared to run as an always-on Docker Compose app on an OCI Ampere A1 ARM64 VM.

## Recommended OCI Shape

- Shape: `VM.Standard.A1.Flex`
- OCPUs: `1` or `2`
- Memory: `4 GB` minimum, `6-12 GB` preferred if `EXPORT_FINBERT=1`
- OS image: Ubuntu Always Free eligible image
- Boot volume: default `50 GB` is enough for app state and Docker layers

Oracle Always Free currently allows Ampere A1 resources within the account limits, but capacity can vary by region. If provisioning fails with capacity errors, retry another availability domain or later.

## First-Time Server Bootstrap

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in so the `docker` group takes effect.

## Deploy

```bash
git clone https://github.com/getanirao/glassbox-finance.git
cd glassbox-finance
cp .env.example .env
nano .env
```

Set:

```env
BOT_TOKEN=...
WEBHOOK_URL=...
RUN_MODE=COMPETITION
DOCKER_PLATFORM=linux/arm64
EXPORT_FINBERT=0
```

Then start the always-on bot + engine:

```bash
docker compose up -d --build
docker compose logs -f --tail 100
```

## Optional MarketWatch Bridge

The passive browser bridge requires a dedicated public HTTPS hostname. Keep the Docker port loopback-bound and let a TLS reverse proxy be the only public entry point.

1. Add these values to the server `.env` file:

```env
MARKETWATCH_SYNC_ENABLED=true
MARKETWATCH_SYNC_BIND_ADDRESS=127.0.0.1
MARKETWATCH_SYNC_PORT=8765
MARKETWATCH_SYNC_TOKEN=<at-least-32-random-characters>
MARKETWATCH_GAME_SLUG=wolves-of-wall-street---july-2026
```

Generate the token on the server with `openssl rand -hex 32`. Do not reuse the Discord bot token or webhook URL.

2. Point a hostname such as `bridge.example.com` at the VM and configure Caddy on the host:

```caddyfile
bridge.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

Caddy obtains and renews TLS certificates automatically once DNS and ports 80/443 are available. Do not open port 8765 in the OCI security list or host firewall.

3. Rebuild and verify the receiver:

```bash
docker compose up -d --build
curl --fail https://bridge.example.com/v1/marketwatch/health
```

4. Load `marketwatch-bridge` as an unpacked extension in Chrome, configure its options with `https://bridge.example.com` and the bridge token, then open the signed-in Wolves Portfolio page. The first successful snapshot establishes a no-trade baseline. Do not rely on executable Glassbox instructions until the page badge and Discord dashboard both report `healthy`.

If the bridge reports a cash/share mismatch, it intentionally blocks final recommendations; inspect the MarketWatch activity table and Glassbox ledger before clearing or re-baselining.

## Optional Local News Worker

The main container already runs the news cycle. If you want an additional local worker sharing the same Docker volume, enable the worker profile:

```bash
docker compose --profile worker up -d --build
```

Do this only if you want more frequent cache refreshes. The file lock prevents overlap, but it is still extra yfinance traffic.

## FinBERT Model Export

`EXPORT_FINBERT=0` is the default for Oracle ARM because it avoids pulling PyTorch during image build. The runtime will use the Loughran-McDonald fallback scorer unless `/app/models/finbert_quantized.onnx` exists.

If the VM has enough RAM and build time is acceptable, enable:

```env
EXPORT_FINBERT=1
```

Then rebuild:

```bash
docker compose build --no-cache
docker compose up -d
```

## Updating

```bash
git pull --ff-only
docker compose up -d --build
docker compose logs -f --tail 100
```

## Backups

State lives in the `glassbox_data` Docker volume. To snapshot:

```bash
docker run --rm -v glassbox-finance_glassbox_data:/data -v "$PWD":/backup busybox \
  tar czf /backup/glassbox-data-backup.tgz -C /data .
```
