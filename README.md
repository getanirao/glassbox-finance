# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine providing real-time sentiment-driven BUY/HOLD/SELL recommendations for a 12-week stock competition. Human-in-the-loop: the engine recommends, the user executes on MarketWatch VSE, and the optional passive bridge reconciles the visible MarketWatch portfolio/activity tables back into Glassbox.

## Current System Status

- **Live Financial Data Ingestion Active via yfinance** — Fundamental data (income statements, balance sheets, valuation ratios) cached for 24 hours to avoid Yahoo rate limits. News headlines and sentiment still fetched every 60-min cycle. Sentiment and price data stream at full frequency.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and total Debt-to-Equity from live balance-sheet data, rejecting invalid balance-sheet inputs as well as CR < 1.2 or D/E > 1.5. Financial institutions (JPM, GS, BAC, MS, C) retain a neutral baseline score of 75.0.
- **ROE + P/E (P/B for Banks) Valuation Multiplier Active** — After solvency, `health_score` is multiplied by a blended factor: 50/50 ROE+P/E for non-banks, 70/30 ROE+P/B for banks. ROE normalized to 20% par (cap 0.5–1.5×). P/E sweet spot 10–20×; P/B sweet spot 1.0–1.5×. Prevents overvaluing high-ROE expensive stocks.
- **Market-Open Recommendation Gate Active** — Final BUY/HOLD/SELL instructions are issued at most once per configured 4-hour gate and only during NYSE market hours. Off-hours dashboards are explicitly previews.
- **FinBERT Sentiment Scoring (ONNX Quantized)** — `ProsusAI/finbert` can be exported to INT8 ONNX at Docker build time with `EXPORT_FINBERT=1`; runtime inference uses `onnxruntime` when the model exists. Temperature scaling (T=0.5) applies to logits before softmax. Loughran-McDonald remains the offline fallback, surfaced both in startup logs and with a degraded-engine Discord dashboard alert.
- **75-Ticker Watchlist Scanner Active** — Broad-market universe across Technology, Healthcare, Energy, Consumer Cyclical, Industrials, Utilities, and Finance. Top 12 per cycle by blended solvency + sentiment score.
- **Safe Competition Reset Available** — `python main.py --clear` waits for the engine and shared news lock, removes both news-cache files plus all competition state, purges stored Discord dashboard messages, and preserves `PIPELINE.md` audit history.
- **Bounded BUY/HOLD/SELL Recommendations Active** — The top 12 are screened at the configured sentiment threshold. Up to six new names receive score-weighted allocations capped at 30% each; existing holdings do not receive duplicate BUYs. A holding exits when it drops out of the top 12 or turns negative. Stop-loss, trim, and profit-taking exits are each explicitly tracked so a logged partial exit cannot repeat every cycle.
- **Validated Trade Logging via `/trade`** — After executing on MarketWatch VSE, user logs the actual fill, for example `/trade ticker:CSCO action:buy shares:100 price:52.40`. The ledger rejects unsupported tickers, insufficient cash, oversells, and positions beyond the holding limit before updating cash, shares, and chart history.
- **Passive MarketWatch Portfolio Bridge Ready** — The unpacked Manifest V3 extension observes only the visible Wolves Portfolio/activity tables, keeps an IndexedDB retry outbox, and replays acknowledged MarketWatch fills with their original timestamps. It never submits a MarketWatch order. The model fails closed when the visible cash or shares cannot be reconciled with the imported ledger.
- **NYSE Market Clock Gate Active** — Detects US Eastern Time and applies the 2026 NYSE full-day holiday and 1:00 PM ET early-close calendar. Final execution recommendations restricted to regular market hours. Predicted allocation updates continuously during off-hours as sentiment evolves.
- **Continuous 60-Minute News Stream Active** — Scrapes headlines for all 75 tickers every 60 minutes, 24/7/365. A shared atomic lock plus reload-before-save coordination prevents engine/worker cache clobbering. Each cycle compiles one batched **News Roundup** Discord message, hard-capped at 2000 characters.
- **Bounded Rolling News Cache Active** — Persistent `.news_cache.json` uses normalized title deduplication, publisher timestamps when available, and a 30-headline per-ticker cap within the adaptive time window.
- **Optional Article Summarization Wired** — When `ENABLE_ARTICLE_SUMMARIZATION=true`, fetched article bodies are summarized by the configured provider before scoring; the default remains headline-only to avoid API cost and external dependencies.
- **Decay-Weighted Rolling Sentiment Architecture Online** — Two independent sentiment horizons. Short-term uses adaptive window (24h Tue–Thu / 72h Fri–Mon). Long-term uses 504-hour (21-day) trend anchor. Both windows apply **exponential decay weighting** with 336-hour (14-day) half-life. Blended penalty (`0.7 × short + 0.3 × long`) smooths noise.
- **Relevance-Weighted Sentiment with FinBERT** — Headline relevance multipliers: 3× for ticker symbol mentions, 2× for company name, 0.33× for unrelated feed content. Ticker-relevant negative headlines receive downside-risk weighting, and business-loss phrases such as losing viewers/subscribers are floored negative so displayed headlines align with the rolling score. FinBERT ONNX is loaded from the configured model directory when present, with the Loughran-McDonald lexicon as fallback.
- **Self-Repairing News Cache** — On every engine startup, `repair_news_cache()` re-scans cached headlines with current scorer and corrects stale scores.
- **Crash-Protected Cache Backup** — Before overwriting a healthy `.news_cache.json`, the prior state is copied to `.news_cache.backup.json`. Only an unreadable main cache restores from backup; a missing cache is always treated as an intentional fresh start.
- **Adaptive Weekend Cache Horizon Online** — Tue–Thu: 24h window. Fri–Mon: 72h window preserving weekend corporate news.
- **Two-Clock Architecture Active** — **60-min news clock** fetches headlines, runs full ticker evaluation, updates predicted allocation on dashboard. **60-sec visualization clock** refreshes portfolio value, regenerates chart, and PATCHes the competition dashboard with live spot prices.
- **Self-Editing Discord Competition Dashboard Active** — Shows real holdings table (ticker, shares, avg price, current price, value, unrealized P&L), predicted top-12 allocation with BUY/HOLD/SELL recommendations, and portfolio chart. PATCHed every 60 seconds. 404 recovery clears stale message ID and auto-posts new message.
- **Automated Discord Message Purge on Reset** — `--clear` sends HTTP DELETE to remove competition dashboard and news roundup messages from channel history before cleaning local state.
- **Oracle Always Free ARM Deployment Ready** — Docker now targets `linux/arm64` by default, uses Python 3.12 multi-arch images, and makes FinBERT ONNX export opt-in (`EXPORT_FINBERT=1`) so the app can run on OCI Ampere A1 without a heavyweight PyTorch build.
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
docker compose up -d --build              # Build and start bot + engine on Oracle ARM
docker compose --profile worker up -d     # Optional local news worker sharing same volume
docker compose logs -f                    # Follow logs
docker compose down                       # Stop gracefully
docker compose exec glassbox python main.py --clear  # Reset state
```

See `ORACLE_ALWAYS_FREE_SETUP.md` for the full OCI Ampere A1 bootstrap and `POSTGRES_STORAGE_HANDOFF.md` for the future Neon/Postgres shared-cache migration plan.

### MarketWatch Bridge

The bridge is intentionally disabled by default. It needs a dedicated public **HTTPS** hostname that reverse-proxies only to the loopback-bound Docker port; do not expose port `8765` directly to the internet.

1. Set `MARKETWATCH_SYNC_ENABLED=true` and a unique `MARKETWATCH_SYNC_TOKEN` of at least 32 characters in the Oracle `.env` file.
2. Configure Caddy, Nginx, or a managed HTTPS tunnel to proxy `https://your-host/v1/marketwatch/*` to `http://127.0.0.1:8765` on the server.
3. Run `docker compose up -d --build`, then visit `https://your-host/v1/marketwatch/health` to confirm the receiver is reachable.
4. In Chrome, open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `marketwatch-bridge` folder in this repository.
5. Open the extension options, enter the public HTTPS origin and bridge token, then visit the signed-in Wolves **Portfolio** page. Wait for the page badge and Discord dashboard to say `healthy` before relying on final trade instructions.

The baseline step reads the current portfolio only; it creates no MarketWatch transaction. Existing cash-only chart points do not block a baseline, but any prior recorded trade does. A blocked or stale bridge converts the Discord dashboard to preview-only until the mismatch is resolved.

### Config Constants (`config.py`)
| Constant | Value | Purpose |
| :--- | :--- | :--- |
| `STARTING_CAPITAL` | 100000 | Initial virtual cash |
| `GATE_HOURS` | 4 | Cooldown between final market-open recommendation cycles |
| `WATCHLIST_SCANNER_LIMIT` | 75 | Tickers in watchlist |
| `MAX_PORTFOLIO_HOLDINGS` | 12 | Max positions funded |
| `MAX_BUYS_PER_CYCLE` | 6 | Max new BUY recommendations per cycle |
| `LONG_WINDOW_HOURS` | 504 | 21-day sentiment trend anchor |
| `LONG_SENTIMENT_WEIGHT` | 0.3 | Blending weight for long-term sentiment |
| `DECAY_HALF_LIFE_HOURS` | 336 | 14-day decay half-life |
| `FINBERT_TEMPERATURE` | 0.5 | Logit temperature scaling (T<1 sharpens) |
| `SENTIMENT_BUY_THRESHOLD` | 0.0 | Minimum sentiment for BUY decision |
| `NEWS_CYCLE_HOURS` | 1 | News stream frequency |
| `MAX_HEADLINES_PER_TICKER` | 30 | Per-ticker cache cap inside the active time window |
| `EXECUTION_WINDOW_MINUTES` | 15 | Advisory window (user can trade anytime) |
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
- **60-min news clock**: Fetches headlines → runs full solvency + sentiment eval → updates predicted top-12 → PATCHes dashboard
- **60-sec visualization clock**: Pulls spot prices → computes portfolio value → regenerates chart → PATCHes dashboard with live data

### Discord Bot Commands
| Command | Description |
| :--- | :--- |
| `/status` | Engine mode, market state, portfolio value |
| `/news` | News cache summary with short + 21d sentiment |
| `/history` | Last 20 portfolio value entries |
| `/chart` | Latest competition chart image |
| `/trade` | Log an actual fill: `ticker:CSCO action:buy shares:100 price:52.40` (optional `time` in HH:MM UTC) |
| `/bulk-trade` | Multiple fills: one `TICKER ACTION SHARES PRICE [TIME]` per line; `TICKER HOLD` supported |
| `/hold` | Confirm a HOLD: `ticker:MSFT` |
| `/help` | Command list |
| `/pause` | Pause engine (Admin) |
| `/resume` | Resume engine (Admin) |
| `/stop` | Graceful stop (Admin) |
| `/clear` | Full reset (Admin) |

Trader role is required for query/trade commands; Admin role is required for engine controls and reset.

## Features Implemented

> Phase 1 — Foundation & Instrumentation
