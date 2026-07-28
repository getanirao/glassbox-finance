# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine providing real-time sentiment-driven BUY/HOLD/SELL recommendations for a 12-week stock competition. Human-in-the-loop: the engine recommends, the user executes on MarketWatch VSE, and the optional passive bridge reconciles the visible MarketWatch portfolio/activity tables back into Glassbox.

## Current System Status

- **Competition Readiness Qualification Complete** — The fully pinned Docker image completed a live 75-ticker news and ranking cycle without errors, retained the reconciled `$100,000` cash-only baseline, and automatically restored authenticated MarketWatch heartbeats across receiver restarts. Nine Python safety regressions and four browser-parser fixtures pass; post-cycle container usage returns to approximately 0% CPU and 359 MiB memory.
- **Live Financial Data Ingestion Active via yfinance** — Fundamental data (income statements, balance sheets, valuation ratios) cached for 24 hours to avoid Yahoo rate limits. News headlines and sentiment still fetched every 60-min cycle. Sentiment and price data stream at full frequency.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and total Debt-to-Equity from live balance-sheet data, rejecting invalid balance-sheet inputs as well as CR < 1.2 or D/E > 1.5. Financial institutions (JPM, GS, BAC, MS, C) retain a neutral baseline score of 75.0.
- **ROE + P/E (P/B for Banks) Valuation Multiplier Active** — After solvency, `health_score` is multiplied by a blended factor: 50/50 ROE+P/E for non-banks, 70/30 ROE+P/B for banks. ROE normalized to 20% par (cap 0.5–1.5×). P/E sweet spot 10–20×; P/B sweet spot 1.0–1.5×. Prevents overvaluing high-ROE expensive stocks.
- **Market-Open Recommendation Gate Active** — Final BUY/HOLD/SELL instructions are issued at most once per configured 4-hour gate and only during NYSE market hours. Off-hours dashboards are explicitly previews.
- **ModernFinBERT Sentiment Scoring (ONNX Quantized)** — `tabularisai/ModernFinBERT` is exported to INT8 ONNX by default at Docker build time; runtime inference uses `onnxruntime` with two intra-op CPU threads. Temperature scaling (T=0.5) applies to logits before softmax. Loughran-McDonald remains the fail-visible offline fallback, surfaced both in startup logs and with a degraded-engine Discord dashboard alert.
- **75-Ticker Watchlist Scanner Active** — Broad-market universe across Technology, Healthcare, Energy, Consumer Cyclical, Industrials, Utilities, and Finance. Top eight by blended solvency + sentiment score are reviewed each cycle.
- **Safe Competition Reset Available** — `python main.py --clear` waits for the engine and shared news lock, removes both news-cache files plus all competition state, purges stored Discord dashboard messages, and preserves `PIPELINE.md` audit history.
- **Conviction-Gated Eight-Name Portfolio Active** — Six core slots require at least `+0.15` sentiment; the final two slots require both current and 21-day sentiment of at least `+0.35` plus 72 hours of accumulated coverage. New positions are capped at two per sector and two in the shared growth/AI factor. BUY sizing preserves at least 10% cash, while the scorecard labels every non-trade as `SKIP` or `DEFER` with its reason.
- **MarketWatch-Only Durable Trade Ledger Active** — Discord is read-only for recommendations and monitoring. The passive bridge is the sole route for executed MarketWatch fills, original timestamps, cash, and holdings into the verified Glassbox ledger. Trade events are retained in an uncapped journal independent of observation-history trimming, protected by an atomic backup, and viewable with `/trades`.
- **Persistent Execution Plans Active** — Market-open BUY/SELL instructions are stored for 15 minutes and survive 60-second dashboard refreshes and container restarts. Imported MarketWatch fills decrement the remaining quantity; a fully acknowledged plan clears automatically.
- **Local-Only MarketWatch Portfolio Bridge Active** — The unpacked Manifest V3 extension connects directly to the loopback Docker receiver, observes only the visible Wolves Portfolio/activity tables, keeps an IndexedDB retry outbox, and uses a one-minute browser alarm to request a fresh snapshot while the signed-in Portfolio page is open. It selects tables by visible Portfolio/activity context, requires the visible `Cash Remaining` value, self-heals a disconnected content script, preserves seconds when MarketWatch exposes them, and never submits a MarketWatch order. Temporary incomplete page renders remain retryable instead of permanently poisoning baseline state.
- **Bridge Status Popup and Empty-Portfolio Baseline Active** — Clicking the extension icon opens its sync status and settings control. A visible “no holdings” Portfolio state is treated as a complete empty baseline, avoiding a test trade at competition start.
- **NYSE Market Clock Gate Active** — Detects US Eastern Time and applies the 2026 NYSE full-day holiday and 1:00 PM ET early-close calendar. Final execution recommendations restricted to regular market hours. Predicted allocation updates continuously during off-hours as sentiment evolves.
- **Continuous 60-Minute News Stream Active** — Scrapes headlines for all 75 tickers every 60 minutes, 24/7/365. A shared Linux advisory lock, with an atomic-file fallback outside Linux, prevents engine/worker cache clobbering and releases automatically when a container exits. Each cycle compiles one batched **News Roundup** Discord message, hard-capped at 2000 characters.
- **Bounded 21-Day News Cache Active** — Persistent `.news_cache.json` uses normalized title deduplication and publisher timestamps. It keeps at most 30 headlines per ticker inside the adaptive short window and a five-headline-per-ticker-per-day sample for the remainder of the 21-day horizon.
- **Optional Article Summarization Wired** — When `ENABLE_ARTICLE_SUMMARIZATION=true`, fetched article bodies are summarized by the configured provider before scoring; the default remains headline-only to avoid API cost and external dependencies.
- **Decay-Weighted Rolling Sentiment Architecture Online** — Two independent sentiment horizons. Short-term uses adaptive window (24h Tue–Thu / 72h Fri–Mon). Long-term uses 504-hour (21-day) trend anchor. Both windows apply **exponential decay weighting** with 336-hour (14-day) half-life. Blended penalty (`0.7 × short + 0.3 × long`) smooths noise.
- **Relevance-Weighted Sentiment with FinBERT** — Headline relevance multipliers: 3× for ticker symbol mentions, 2× for company name, 0.33× for unrelated feed content. Ticker-relevant negative headlines receive downside-risk weighting, and business-loss phrases such as losing viewers/subscribers are floored negative so displayed headlines align with the rolling score. FinBERT ONNX is loaded from the configured model directory when present, with the Loughran-McDonald lexicon as fallback.
- **Versioned Self-Repairing News Cache** — On engine startup, the cache is re-scored only when the scorer/backend version changes and the migration tag is persisted immediately, avoiding repeated full-cache CPU spikes across restarts.
- **Crash-Protected Cache Backup** — Before overwriting a healthy `.news_cache.json`, the prior state is copied to `.news_cache.backup.json`. Only an unreadable main cache restores from backup; a missing cache is always treated as an intentional fresh start.
- **Adaptive Weekend Cache Horizon Online** — Tue–Thu: 24h window. Fri–Mon: 72h window preserving weekend corporate news.
- **Two-Clock Architecture Active** - **60-min news clock** fetches headlines, runs full ticker evaluation, and updates the predicted allocation. **60-sec portfolio clock** refreshes portfolio value and PATCHes the Discord dashboard; numeric history is retained every five minutes without generating chart images.
- **Self-Editing Discord Competition Dashboard Active** - Shows real holdings table (ticker, shares, avg price, current price, value, unrealized P&L) and predicted top-eight allocation with model `Score`, sentiment, fundamental `Health`, and intended `Wt` allocation. These are clearly labeled as non-price signals; live yfinance quotes are used separately for order sizing. PATCHed every 60 seconds. 404 recovery clears stale message ID and auto-posts a new message.
- **Supervised Runtime and Healthcheck Active** — The bot process watches the engine thread every five seconds and exits on engine failure so Docker can restart the complete service. A timestamped engine heartbeat drives the container healthcheck, and runtime dependency versions are pinned to the audited build.
- **Automated Discord Message Purge on Reset** — `--clear` sends HTTP DELETE to remove competition dashboard and news roundup messages from channel history before cleaning local state.
- **Native Laptop and Oracle ARM Deployment Ready** — Docker defaults to `linux/amd64` for responsive local FinBERT inference and exports the ONNX model by default. Set `DOCKER_PLATFORM=linux/arm64` on OCI Ampere A1; Python 3.12 images remain multi-architecture.
- **News Worker Roles Available** — `--news-worker` and `--news-worker-once` run fetch/score-only cycles without Discord dashboards or recommendations. Local engine/worker containers coordinate through an atomic stale-aware news lock. GitHub Actions snapshots are inspection artifacts only and do not feed the Oracle cache until shared storage is implemented.

## Command Reference

### Terminal Execution
```bash
python main.py --comp --bot              # Engine + Discord bot (competition mode)
python main.py --engine                  # Engine only, no Discord bot
python main.py --news-worker             # Continuous fetch/score news worker only
python main.py --news-worker-once        # One fetch/score cycle for cron/GitHub Actions
python main.py --bot-only                 # Discord bot only, no engine
python main.py --clear                    # Purge all state + Discord messages
python main.py --help                     # Show usage
```

### Command-Line Arguments
| Argument | Outcome |
| :--- | :--- |
| `--comp` | Competition advisory mode (default) |
| `--bot` | Start Discord bot alongside engine |
| `--bot-only` | Start only the Discord bot |
| `--engine` | Start only the recommendation engine |
| `--news-worker` | Continuously fetch and score news without Discord output |
| `--news-worker-once` | Fetch and score news once, then exit |
| `--clear` | Safely purge competition state and stored Discord messages while preserving audit logs |

### Docker
```bash
docker compose up -d --build              # Build and start bot + engine on this x86_64 laptop
DOCKER_PLATFORM=linux/arm64 docker compose up -d --build  # Oracle Ampere A1
docker compose --profile worker up -d     # Optional local news worker sharing same volume
docker compose logs -f                    # Follow logs
docker compose ps                         # Verify service heartbeat health
docker compose down                       # Stop gracefully
docker compose exec glassbox python main.py --clear  # Reset state
```

See `ORACLE_ALWAYS_FREE_SETUP.md` for the full OCI Ampere A1 bootstrap and `POSTGRES_STORAGE_HANDOFF.md` for the future Neon/Postgres shared-cache migration plan.

### MarketWatch Bridge

The bridge is intentionally disabled by default. For this local Docker deployment, use the loopback endpoint `http://127.0.0.1:8765`; traffic never leaves this PC. A remote deployment instead needs a dedicated public **HTTPS** hostname that reverse-proxies only to the loopback-bound Docker port; do not expose port `8765` directly to the internet.

1. Create `.marketwatch-bridge.env` from `marketwatch-bridge.env.example`, set `MARKETWATCH_SYNC_ENABLED=true`, and use a unique `MARKETWATCH_SYNC_TOKEN` of at least 32 characters.
2. Run `docker compose up -d --build`, then visit `http://127.0.0.1:8765/v1/marketwatch/health` to confirm the local receiver is reachable.
3. In Chrome, open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `marketwatch-bridge` folder in this repository.
4. Open the extension options, enter `http://127.0.0.1:8765` and the bridge token, then visit the signed-in Wolves **Portfolio** page. Wait for the page badge and Discord dashboard to say `healthy` before relying on final trade instructions.

The baseline step reads the current portfolio only; it creates no MarketWatch transaction. A complete baseline requires both visible holdings state and the visible `Cash Remaining` value. Existing cash-only chart points do not block a baseline, and a bridge-owned ledger can recover from a temporary partial first render without clearing state. A blocked or stale bridge converts the Discord dashboard to preview-only until reconciliation is healthy. Keep the signed-in Wolves Portfolio tab open during a market-open recommendation window so its one-minute heartbeat keeps the bridge healthy. Execute final BUY/SELL instructions on MarketWatch only; the bridge records the fill automatically, so Discord has no trade-entry commands.

### Config Constants (`config.py`)
| Constant | Value | Purpose |
| :--- | :--- | :--- |
| `STARTING_CAPITAL` | 100000 | Initial virtual cash |
| `GATE_HOURS` | 4 | Cooldown between final market-open recommendation cycles |
| `WATCHLIST_SCANNER_LIMIT` | 75 | Tickers in watchlist |
| `CORE_PORTFOLIO_HOLDINGS` | 6 | Core positions funded at standard conviction |
| `MAX_PORTFOLIO_HOLDINGS` | 8 | Absolute portfolio maximum |
| `MAX_BUYS_PER_CYCLE` | 8 | Max new BUY recommendations per cycle |
| `MIN_CASH_RESERVE_PERCENT` | 0.10 | Minimum cash left after planned BUY allocations |
| `SENTIMENT_BUY_THRESHOLD` | 0.15 | Minimum current sentiment for a core BUY |
| `PERSISTENT_SENTIMENT_THRESHOLD` | 0.35 | Minimum current and 21d sentiment for a reserve slot |
| `MIN_PERSISTENT_COVERAGE_HOURS` | 72 | Required cache age before a reserve slot can activate |
| `MAX_SECTOR_POSITIONS` | 2 | Maximum new exposure per configured sector |
| `MAX_FACTOR_POSITIONS` | 2 | Maximum new shared growth/AI exposure |
| `LONG_WINDOW_HOURS` | 504 | 21-day sentiment trend anchor |
| `LONG_SENTIMENT_WEIGHT` | 0.3 | Blending weight for long-term sentiment |
| `DECAY_HALF_LIFE_HOURS` | 336 | 14-day decay half-life |
| `FINBERT_TEMPERATURE` | 0.5 | Logit temperature scaling (T<1 sharpens) |
| `FINBERT_INTRA_OP_THREADS` | 2 | ONNX CPU threads used for sentiment inference |
| `NEWS_CYCLE_HOURS` | 1 | News stream frequency |
| `MAX_HEADLINES_PER_TICKER` | 30 | Per-ticker cache cap inside the active time window |
| `MAX_LONG_HEADLINES_PER_TICKER_DAY` | 5 | Per-day sample retained outside the short window |
| `EXECUTION_WINDOW_MINUTES` | 15 | Persisted final-plan lifetime and fill-matching window |
| `INSTITUTIONAL_BANKS` | JPM,GS,BAC,MS,C | Skip solvency gate for banks |
| `TRAILING_TRIM_PERCENT` | 0.05 | Partial position trim (-5%) — sell half |
| `PROFIT_TAKE_PERCENT` | 0.10 | Profit-taking threshold (+10%) — sell half |
| `ENABLE_ARTICLE_SUMMARIZATION` | False | Use LLM to summarize article body before scoring |
| `SUMMARIZE_PROVIDER` | `openai` | LLM provider: `openai`, `anthropic`, or `gemini` |
| `SUMMARIZE_MAX_CHARS` | 4000 | Max characters to send for summarization |

### Market State Flags
- **`MARKET_OPEN`**: NYSE trading hours (9:30 AM–4:00 PM ET, Mon–Fri). Final recommendations unlocked.
- **`ANALYTICAL_OFF_HOURS`**: Outside market hours. Predicted allocation updates but no final recommendations.

### Two-Clock Architecture
- **60-min news clock**: Fetches headlines → runs full solvency + sentiment eval → updates predicted top-eight → PATCHes dashboard
- **60-sec portfolio clock**: Pulls spot prices → computes portfolio value → PATCHes dashboard and records numeric history every five minutes

### Discord Bot Commands
| Command | Description |
| :--- | :--- |
| `/status` | Engine mode, market state, portfolio value |
| `/news` | News cache summary with short + 21d sentiment |
| `/history` | Last 20 portfolio value entries |
| `/trades` | Durable MarketWatch execution journal |
| `/help` | Command list |
| `/pause` | Pause engine (Admin) |
| `/resume` | Resume engine (Admin) |
| `/stop` | Graceful stop (Admin) |
| `/clear` | Full reset (Admin) |

Trader role is required for query commands; Admin role is required for engine controls and reset. Execute trades on MarketWatch only; the local bridge imports verified fills automatically.

## Features Implemented

> Phase 1 — Foundation & Instrumentation
