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
