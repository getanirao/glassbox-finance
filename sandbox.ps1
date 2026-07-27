$env:RUN_MODE = "COMPETITION"
docker compose down 2>$null
docker compose up -d --build
docker logs -f glassbox-finance
