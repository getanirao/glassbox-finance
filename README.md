# Glassbox Finance — Wolves of Wall Street

Quantitative finance engine providing real-time sentiment-driven BUY/HOLD/SELL recommendations for a 12-week stock competition. Human-in-the-loop: the engine recommends, the user executes on MarketWatch VSE, then logs trades via `/trade` slash command.

## Current System Status

- **Live Financial Data Ingestion Active via yfinance** — Pulls raw income statements, balance sheets, and cash flow statements for all 75 tickers every 60-min news cycle.
- **Solvency Screening Engine Live** — `evaluate_solvency()` computes Current Ratio and Debt-to-Equity Ratio from live balance-sheet data. Assets with CR < 1.2 or D/E > 1.5 are rejected. Financial institutions (JPM, GS, BAC, MS, C) skip solvency gates with a neutral baseline score of 75.0.
- **ROE + P/E (P/B for Banks) Valuation Multiplier Active** — After solvency, `health_score` is multiplied by a blended factor: 50/50 ROE+P/E for non-banks, 70/30 ROE+P/B for banks. ROE normalized to 20% par (cap 0.5–1.5×). P/E sweet spot 10–20×; P/B sweet spot 1.0–1.5×. Prevents overvaluing high-ROE expensive stocks.
- **24-Hour Time Cooldown Gate Active** — Final BUY/HOLD/SELL recommendations issued at most once per 24 hours during NYSE market open. Predicted allocation re-computed every 60-min news cycle regardless of gate or market state.
- **FinBERT Sentiment Scoring (ONNX Quantized)** — `ProsusAI/finbert` exported to INT8 ONNX at Docker build time; runs inference via `onnxruntime` at runtime (no PyTorch). Temperature scaling (T=0.5) applied to logits before softmax to sharpen compressed 3-class scores. Loughran-McDonald lexicon (2,744 words) available as offline fallback.
- **75-Ticker Watchlist Scanner Active** — Broad-market universe across Technology, Healthcare, Energy, Consumer Cyclical, Industrials, Utilities, and Finance. Top 12 per cycle by blended solvency + sentiment score.
- **Manual System Reset Gate Available** — Running `python main.py --clear` wipes news cache, competition ledger, gate timestamp, deletes both Discord dashboard and news roundup messages from channel history, and resets PIPELINE.md log entries.
- **BUY/HOLD/SELL Recommendations Active** — Each 60-min cycle filters predicted top-12 to only sentiment ≥ 0.0, then issues BUY for top 6 (score-weighted allocation from cash), HOLD for owned tickers past the cap, SELL for owned tickers that dropped out or turned negative. Dashboard only shows eligible tickers (no negative sentiment rows). Final recommendations issued with `EXECUTE BY HH:MM UTC` only when gate expired + market open.
- **Trade Logging via `/trade`** — After executing on MarketWatch VSE, user runs `/trade ticker:CSCO action:buy shares:100 price:52.40`. Engine records the trade in `competition_ledger.json`, updates cash balance, share counts, and regenerates the portfolio chart. `/hold` confirms a HOLD recommendation.
- **NYSE Market Clock Gate Active** — Detects US Eastern Time. Final execution recommendations restricted to regular market hours (9:30 AM–4:00 PM ET, Mon–Fri). Predicted allocation updates continuously during off-hours as sentiment evolves.
- **Continuous 60-Minute News Stream Active** — Scrapes headlines for all 75 tickers every 60 minutes, 24/7/365. Jittered 1.5–3.5s sleeps between fetches. File-based lock prevents race conditions. Each cycle compiles a single batched **News Roundup** Discord message (POST/PATCH) with `Last Fetched: HH:MM PT` header, hard-capped at 2000 chars.
- **Deduplicated Rolling News Cache Active** — Persistent `.news_cache.json` stores unique headlines with per-article FinBERT scores. Duplicates across cycles silently skipped.
- **Decay-Weighted Rolling Sentiment Architecture Online** — Two independent sentiment horizons. Short-term uses adaptive window (24h Tue–Thu / 72h Fri–Mon). Long-term uses 504-hour (21-day) trend anchor. Both windows apply **exponential decay weighting** with 336-hour (14-day) half-life. Blended penalty (`0.7 × short + 0.3 × long`) smooths noise.
- **Relevance-Weighted Sentiment with FinBERT** — Headline relevance multipliers: 3× for ticker symbol mentions, 2× for company name, 0.33× for unrelated feed content. FinBERT provides contextual scoring without manual negation detection or keyword boosting.
- **Self-Repairing News Cache** — On every engine startup, `repair_news_cache()` re-scans cached headlines with current scorer and corrects stale scores.
- **Crash-Protected Cache Backup** — Before overwriting `.news_cache.json`, previous healthy state copied to `.news_cache.backup.json` (when ≥50% tickers present). Corrupted cache (<3 tickers) auto-restored from backup.
- **Adaptive Weekend Cache Horizon Online** — Tue–Thu: 24h window. Fri–Mon: 72h window preserving weekend corporate news.
- **Two-Clock Architecture Active** — **60-min news clock** fetches headlines, runs full ticker evaluation, updates predicted allocation on dashboard. **60-sec visualization clock** refreshes portfolio value, regenerates chart, and PATCHes the competition dashboard with live spot prices.
- **Self-Editing Discord Competition Dashboard Active** — Shows real holdings table (ticker, shares, avg price, current price, value, unrealized P&L), predicted top-12 allocation with BUY/HOLD/SELL recommendations, and portfolio chart. PATCHed every 60 seconds. 404 recovery clears stale message ID and auto-posts new message.
- **Automated Discord Message Purge on Reset** — `--clear` sends HTTP DELETE to remove competition dashboard and news roundup messages from channel history before cleaning local state.

## Command Reference

### Terminal Execution
```bash
python main.py --comp --bot              # Engine + Discord bot (competition mode)
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
| `--clear` | Purge state files, delete Discord messages, reset PIPELINE.md |

### Docker
```bash
docker compose up -d                      # Build and start
docker compose logs -f                    # Follow logs
docker compose down                       # Stop gracefully
docker compose exec glassbox python main.py --clear  # Reset state
```

### Config Constants (`config.py`)
| Constant | Value | Purpose |
| :--- | :--- | :--- |
| `STARTING_CAPITAL` | 100000 | Initial virtual cash |
| `GATE_HOURS` | 24 | Cooldown between final recommendation cycles |
| `WATCHLIST_SCANNER_LIMIT` | 75 | Tickers in watchlist |
| `MAX_PORTFOLIO_HOLDINGS` | 12 | Max positions funded |
| `MAX_BUYS_PER_CYCLE` | 6 | Max new BUY recommendations per cycle |
| `LONG_WINDOW_HOURS` | 504 | 21-day sentiment trend anchor |
| `LONG_SENTIMENT_WEIGHT` | 0.3 | Blending weight for long-term sentiment |
| `DECAY_HALF_LIFE_HOURS` | 336 | 14-day decay half-life |
| `FINBERT_TEMPERATURE` | 0.5 | Logit temperature scaling (T<1 sharpens) |
| `SENTIMENT_BUY_THRESHOLD` | 0.0 | Minimum sentiment for BUY decision |
| `NEWS_CYCLE_HOURS` | 1 | News stream frequency |
| `EXECUTION_WINDOW_MINUTES` | 1 | Time to execute after final recommendation |
| `INSTITUTIONAL_BANKS` | JPM,GS,BAC,MS,C | Skip solvency gate for banks |

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
| `/holdings` | Current positions with live prices |
| `/news` | News cache summary with short + 21d sentiment |
| `/history` | Last 20 portfolio value entries |
| `/chart` | Latest competition chart image |
| `/trade` | Log a trade: `ticker:CSCO action:buy shares:100 price:52.40` |
| `/hold` | Confirm a HOLD: `ticker:MSFT` |
| `/help` | Command list |
| `/pause` | Pause engine (Admin) |
| `/resume` | Resume engine (Admin) |
| `/stop` | Graceful stop (Admin) |
| `/clear` | Full reset (Admin) |
| `/run_comp` | Trigger immediate cycle (Admin) |

All commands visible to everyone. Role checks disabled.

## Features Implemented

> Phase 1 — Foundation & Instrumentation
