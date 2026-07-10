import sys
import os
import math
import json
import time
import datetime
import re
import zoneinfo
import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv
import argparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

load_dotenv()

pd.set_option("display.max_columns", 10)
pd.set_option("display.width", 120)
pd.set_option("display.max_rows", 200)


STARTING_CAPITAL = 100000
GATE_FILE = ".last_run"
GATE_HOURS = 24
LOOP_INTERVAL_MINUTES = 60
SANDBOX_LEDGER = "sandbox_history.json"
NEWS_CACHE_FILE = ".news_cache.json"
ROLLING_WINDOW_HOURS = 24
MESSAGE_STATE_FILE = ".message_state"
NEWS_MESSAGE_STATE_FILE = ".news_message_state"
OBSERVATION_FILE = ".observation_state"
VOLATILITY_THRESHOLD = 0.005
VOLATILITY_WINDOW = 5
GRACE_MINUTES = 30

TICKERS = ["AAPL", "MSFT", "GOOGL", "JPM", "GS", "JNJ", "PFE", "AMZN", "WMT", "XOM"]

INSTITUTIONAL_BANKS = {"JPM", "GS"}

POSITIVE_LEXICON = {
    "revenue", "growth", "beats", "beat", "profit", "upgrade", "upgraded",
    "bullish", "dividend", "earnings", "rally", "outperform", "outperformed",
    "strong", "record", "positive", "raised", "expansion", "guidance",
    "buy", "growing", "profitable", "gains", "surge", "recovery",
    "momentum", "opportunity", "innovation", "confidence", "optimistic",
}

NEGATIVE_LEXICON = {
    "missing", "miss", "lawsuit", "loss", "risk", "downgrade", "downgraded",
    "debt", "bankruptcy", "bearish", "fine", "penalty", "investigation",
    "regulatory", "decline", "fall", "drop", "sell", "below", "weak",
    "warning", "cut", "lower", "fail", "negative", "volatility",
    "short", "underperform", "underperformed", "layoff", "fraud",
}


def load_news_cache():
    if os.path.exists(NEWS_CACHE_FILE):
        with open(NEWS_CACHE_FILE, "r") as f:
            return json.load(f)
    return {"headlines": []}


def save_news_cache(cache):
    with open(NEWS_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def prune_news_cache(cache):
    weekday = datetime.datetime.now(datetime.timezone.utc).weekday()
    if weekday in (1, 2, 3, 4):
        window_hours = 24
    else:
        window_hours = 72
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=window_hours)
    before = len(cache["headlines"])
    surviving = []
    for h in cache["headlines"]:
        try:
            ts = datetime.datetime.fromisoformat(h["timestamp"])
        except (ValueError, KeyError):
            continue
        if ts >= cutoff:
            surviving.append(h)
    cache["headlines"] = surviving
    return before - len(surviving), window_hours


def compute_rolling_sentiment(entries, ticker):
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=ROLLING_WINDOW_HOURS)
    ticker_entries = [
        h for h in entries
        if h["ticker"] == ticker
        and datetime.datetime.fromisoformat(h["timestamp"]) >= cutoff
    ]
    if not ticker_entries:
        return 0.0, 0, 0, 0
    total_net = sum(h["net_score"] for h in ticker_entries)
    avg_net = total_net / len(ticker_entries)
    total_pos = sum(h["pos_count"] for h in ticker_entries)
    total_neg = sum(h["neg_count"] for h in ticker_entries)
    return avg_net, total_pos, total_neg, len(ticker_entries)


def load_message_state():
    if os.path.exists(MESSAGE_STATE_FILE):
        with open(MESSAGE_STATE_FILE, "r") as f:
            return f.read().strip()
    return None


def save_message_state(message_id):
    with open(MESSAGE_STATE_FILE, "w") as f:
        f.write(message_id.strip())


def load_news_message_state():
    if os.path.exists(NEWS_MESSAGE_STATE_FILE):
        with open(NEWS_MESSAGE_STATE_FILE, "r") as f:
            return f.read().strip()
    return None


def save_news_message_state(message_id):
    with open(NEWS_MESSAGE_STATE_FILE, "w") as f:
        f.write(message_id.strip())


def parse_webhook_parts(url):
    base = url.split("?")[0].rstrip("/")
    parts = base.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, None


def load_observation_state():
    if os.path.exists(OBSERVATION_FILE):
        with open(OBSERVATION_FILE, "r") as f:
            return json.load(f)
    return {"clock_state": "LOCKED", "observation_start": None, "price_log": {}}


def save_observation_state(state):
    with open(OBSERVATION_FILE, "w") as f:
        json.dump(state, f, indent=2)


def collect_spot_prices(state, tickers):
    now = datetime.datetime.now(datetime.timezone.utc)
    if "price_log" not in state:
        state["price_log"] = {}
    for ticker in tickers:
        if ticker not in state["price_log"]:
            state["price_log"][ticker] = []
        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.last_price
            if price is None or price <= 0:
                hist = stock.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else None
            if price and price > 0:
                state["price_log"][ticker].append({"t": now.isoformat(), "p": price})
                if len(state["price_log"][ticker]) > 10:
                    state["price_log"][ticker] = state["price_log"][ticker][-10:]
        except Exception:
            pass


def compute_volatility_spread(price_log):
    spreads = []
    for ticker, prices in price_log.items():
        if len(prices) < 2:
            continue
        recent = [p["p"] for p in prices[-VOLATILITY_WINDOW:]]
        if len(recent) < 2:
            continue
        returns = [(recent[i] - recent[i-1]) / recent[i-1] for i in range(1, len(recent))]
        if not returns:
            continue
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        spreads.append(math.sqrt(variance))
    if not spreads:
        return float('inf')
    return sum(spreads) / len(spreads)


def volatility_stabilized(state):
    if state.get("clock_state") != "OBSERVING":
        return False
    obs_start = datetime.datetime.fromisoformat(state["observation_start"])
    elapsed = datetime.datetime.now(datetime.timezone.utc) - obs_start
    if elapsed >= datetime.timedelta(minutes=GRACE_MINUTES):
        return True
    spread = compute_volatility_spread(state.get("price_log", {}))
    return spread < VOLATILITY_THRESHOLD


def visualization_update():
    ledger = load_sandbox_ledger()
    total_holdings_value = 0
    for ticker, pos in ledger["holdings"].items():
        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.last_price
            if price is None or price <= 0:
                hist = stock.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else 0
        except Exception:
            price = 0
        total_holdings_value += pos["shares"] * price
    portfolio_value = ledger["cash_balance"] + total_holdings_value
    ledger["history"].append({
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "portfolio_value": round(portfolio_value, 2),
    })
    save_sandbox_ledger(ledger)
    generate_portfolio_chart(ledger)
    return ledger


def build_sandbox_status(ledger, clock_state, et_now):
    pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL
    change = pv - STARTING_CAPITAL
    pct = (change / STARTING_CAPITAL) * 100
    arrow = "+" if change >= 0 else ""
    lines = []
    lines.append(f"**Glassbox Finance — SANDBOX DASHBOARD**")
    lines.append(f"Status: MARKET_OPEN — Clock: {clock_state}  |  {et_now.strftime('%H:%M UTC')}")
    lines.append(f"Portfolio: ${pv:,.2f}  ({arrow}{change:,.2f} / {arrow}{pct:.2f}%)")
    lines.append(f"Cash: ${ledger['cash_balance']:,.2f}  |  Holdings: {len(ledger['holdings'])} positions")
    return "\n".join(lines)


def send_or_update_dashboard(payload, image_path=None):
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if not webhook_url:
        print(f"\n  [Discord Sync] Webhook URL not configured.")
        return

    existing_id = load_message_state()
    wh_id, wh_token = parse_webhook_parts(webhook_url)
    if not wh_id or not wh_token:
        print(f"\n  [Discord Sync] Could not parse webhook URL.")
        return

    try:
        if existing_id:
            edit_url = f"https://discord.com/api/webhooks/{wh_id}/{wh_token}/messages/{existing_id}"
            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    resp = requests.patch(
                        edit_url,
                        data={"payload_json": json.dumps({"content": payload, "attachments": []})},
                        files={"file": (os.path.basename(image_path), f, "image/png")},
                        timeout=15
                    )
            else:
                resp = requests.patch(edit_url, json={"content": payload}, timeout=15)
            resp.raise_for_status()
            print(f"\n  [Discord Sync] Dynamic dashboard message ID [{existing_id}] successfully edited in place at 1-minute interval.")
        else:
            post_url = webhook_url.rstrip("/") + "?wait=true"
            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    resp = requests.post(
                        post_url,
                        data={"content": payload},
                        files={"file": (os.path.basename(image_path), f, "image/png")},
                        timeout=15
                    )
            else:
                resp = requests.post(post_url, json={"content": payload}, timeout=15)
            resp.raise_for_status()
            new_id = resp.json().get("id")
            if new_id:
                save_message_state(new_id)
                print(f"\n  [Discord Sync] Initial dashboard message ID [{new_id}] posted and saved.")
            else:
                print(f"\n  [Discord Sync] Dashboard posted but no message ID returned.")
    except Exception as e:
        print(f"\n  [Discord Sync] Dashboard transmission failed - {e}.")


def send_webhook_payload(payload, label, image_path=None):
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if not webhook_url:
        print(f"\n  [Team Desk] Webhook URL not configured — {label} skipped.")
        return
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                resp = requests.post(
                    webhook_url,
                    data={"content": payload},
                    files={"file": (os.path.basename(image_path), f, "image/png")},
                    timeout=15
                )
        else:
            resp = requests.post(webhook_url, json={"content": payload}, timeout=15)
        resp.raise_for_status()
        print(f"\n  [Team Desk] {label} transmitted (HTTP {resp.status_code}).")
    except Exception as e:
        print(f"\n  [Team Desk] {label} transmission failed - {e}.")


def send_news_flash(r):
    ticker = r["ticker"]
    headline = r.get("top_headline", "No headlines available.")
    sent = r["sentiment"]
    rp = r["rolling_pos"]
    rn = r["rolling_neg"]
    rc = r["rolling_count"]
    directive = r.get("directive", "Insufficient data for directive.")

    lines = []
    lines.append(f"NEWS [{ticker}] Real-Time Market Feed Alert")
    lines.append(f"")
    lines.append(f"  Headline Scanned: \"{headline}\"")
    lines.append(f"  Rolling Sentiment: Score: {sent:+.2f} (24h Window: {rp} Pos, {rn} Neg across {rc} unique articles)")
    lines.append(f"  System Directive: {directive}")

    payload = "\n".join(lines)
    send_webhook_payload(payload, f"News Flash - {ticker}")


def summarize_news_entry(ticker, headlines, rolling_sent, rolling_pos, rolling_neg, rolling_count):
    if not headlines:
        return f"{ticker} [{rolling_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> No headlines."

    best_h = headlines[0]
    best_abs = -1.0
    for h in headlines:
        tokens = re.findall(r"[a-z]+", h.lower())
        pos = sum(1 for t in tokens if t in POSITIVE_LEXICON)
        neg = sum(1 for t in tokens if t in NEGATIVE_LEXICON)
        total = pos + neg
        net = (pos - neg) / total if total > 0 else 0.0
        if abs(net) > best_abs:
            best_abs = abs(net)
            best_h = h

    if len(best_h) > 130:
        truncated = best_h[:130]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        best_h = truncated + "\u2026"

    return f"{ticker} [{rolling_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> {best_h}"


def build_news_roundup(alerts, et_now):
    lines = []
    lines.append("=" * 80)
    lines.append("                         GLASSBOX NEWS ROUNDUP")
    lines.append("=" * 80)
    for r in alerts:
        row = summarize_news_entry(
            r["ticker"], r.get("headlines", []),
            r["sentiment"], r["rolling_pos"], r["rolling_neg"], r["rolling_count"]
        )
        lines.append(f"  {row}")
    lines.append("=" * 80)
    lines.append(f"  Timestamp: {et_now.strftime('%Y-%m-%d %H:%M %Z')}  |  24h Rolling Window Active")
    lines.append("=" * 80)
    return "\n".join(lines)


def send_batched_news(alerts, et_now):
    if not alerts:
        return
    payload = build_news_roundup(alerts, et_now)

    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if not webhook_url:
        print("\n  [News Roundup] Webhook URL not configured.")
        return

    wh_id, wh_token = parse_webhook_parts(webhook_url)
    if not wh_id or not wh_token:
        print("\n  [News Roundup] Could not parse webhook URL.")
        return

    existing_id = load_news_message_state()

    try:
        if existing_id:
            edit_url = f"https://discord.com/api/webhooks/{wh_id}/{wh_token}/messages/{existing_id}"
            resp = requests.patch(edit_url, json={"content": payload}, timeout=15)
        else:
            post_url = webhook_url.rstrip("/") + "?wait=true"
            resp = requests.post(post_url, json={"content": payload}, timeout=15)
            msg_id = resp.json().get("id")
            if msg_id:
                save_news_message_state(msg_id)

        resp.raise_for_status()
        print(f"\n  [News Roundup] Transmitted ({len(alerts)} tickers).")
    except Exception as e:
        print(f"\n  [News Roundup] Transmission failed - {e}.")


def build_master_payload(results, market_state, et_now, total_tickers, clock_state=None):
    ranked = sorted(results, key=lambda x: x["adjusted_score"], reverse=True)
    total_score = sum(r["adjusted_score"] for r in ranked) if ranked else 1

    lines = []
    lines.append("**Glassbox Finance - MASTER EXECUTION REPORT**")
    if clock_state:
        lines.append(f"Status: {market_state} — Clock: {clock_state}  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    else:
        lines.append(f"Status: {market_state}  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"Capital: ${STARTING_CAPITAL:,}  |  Universe: {total_tickers} tickers")
    lines.append("")
    lines.append("```")
    header = f"{'Ticker':<8} {'Status':<22} {'Sentiment':>10} {'Alloc %':>10} {'$ Amt':>12} {'Shares':>8}"
    lines.append(header)
    lines.append("-" * len(header))

    for r in ranked:
        score = r["adjusted_score"]
        pct = score / total_score * 100
        dollar_alloc = STARTING_CAPITAL * (pct / 100)

        try:
            stock = yf.Ticker(r["ticker"])
            price = stock.fast_info.last_price
            if price is None or price <= 0:
                hist = stock.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else 0
        except Exception:
            price = 0

        target_shares = int(dollar_alloc / price) if price and price > 0 else 0
        sent_label = f"{r['sentiment']:+.3f}"
        lines.append(f"{r['ticker']:<8} {r['status']:<22} {sent_label:>10} {pct:>9.2f}% ${dollar_alloc:>9,.2f} {target_shares:>7}")

    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<8} {'':<22} {'':>10} {'100.00%':>10} ${STARTING_CAPITAL:>9,.2f} {'':>7}")
    lines.append("```")
    return "\n".join(lines)


def send_master_report(results, market_state, et_now, total_tickers, image_path=None):
    payload = build_master_payload(results, market_state, et_now, total_tickers)
    send_webhook_payload(payload, "Master Execution Report", image_path=image_path)


def check_daily_gate():
    now = datetime.datetime.now(datetime.timezone.utc)
    if not os.path.exists(GATE_FILE):
        return True
    with open(GATE_FILE, "r") as f:
        stored = f.read().strip()
    try:
        last_run = datetime.datetime.fromisoformat(stored)
    except ValueError:
        return True
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=datetime.timezone.utc)
    elapsed = now - last_run
    return elapsed >= datetime.timedelta(hours=GATE_HOURS)


def mark_daily_allocation():
    now = datetime.datetime.now(datetime.timezone.utc)
    with open(GATE_FILE, "w") as f:
        f.write(now.isoformat())


def validate_statement(df, name):
    if df is None or df.empty:
        return False
    if df.isna().all().all():
        return False
    return True


def evaluate_solvency(bs):
    try:
        current_assets = bs.loc[bs.index.str.contains("Current Assets", case=False)].iloc[0, 0]
        current_liabilities = bs.loc[bs.index.str.contains("Current Liabilities", case=False)].iloc[0, 0]
        total_liabilities = bs.loc[bs.index.str.contains("Total Liabilities", case=False)].iloc[0, 0]
        equity = bs.loc[bs.index.str.contains("Stockholders Equity|Stockholder Equity", case=False)].iloc[0, 0]
    except (IndexError, KeyError, AttributeError):
        return None, None, None, None

    current_ratio = current_assets / current_liabilities
    d_to_e = total_liabilities / equity
    cr_score = min(1.0, current_ratio / 1.2)
    de_score = min(1.0, 1.5 / d_to_e)
    health_score = ((cr_score + de_score) / 2) * 100

    if current_ratio < 1.2 or d_to_e > 1.5:
        return False, health_score, current_ratio, d_to_e
    return True, health_score, current_ratio, d_to_e


def sentiment_gate(stock, ticker, news_cache):
    entries = news_cache["headlines"]

    try:
        news_raw = stock.news
    except Exception:
        rolling_sent, rolling_pos, rolling_neg, count = compute_rolling_sentiment(entries, ticker)
        penalty = 1.0
        if rolling_sent < 0.0:
            penalty = 1.0 + (rolling_sent * 0.3)
            penalty = max(0.70, penalty)
        return rolling_sent, penalty, [], rolling_pos, rolling_neg, count

    if not news_raw:
        rolling_sent, rolling_pos, rolling_neg, count = compute_rolling_sentiment(entries, ticker)
        penalty = 1.0
        if rolling_sent < 0.0:
            penalty = 1.0 + (rolling_sent * 0.3)
            penalty = max(0.70, penalty)
        return rolling_sent, penalty, [], rolling_pos, rolling_neg, count

    latest_headlines = []
    new_count = 0

    for article in news_raw:
        content = article.get("content", {})
        title = content.get("title", "") if isinstance(content, dict) else ""
        if not title:
            continue
        latest_headlines.append(title)

        already_seen = any(
            h["text"] == title and h["ticker"] == ticker
            for h in entries
        )
        if already_seen:
            continue

        tokens = re.findall(r"[a-z]+", title.lower())
        pos = sum(1 for t in tokens if t in POSITIVE_LEXICON)
        neg = sum(1 for t in tokens if t in NEGATIVE_LEXICON)
        total = pos + neg
        net = (pos - neg) / total if total > 0 else 0.0
        net = max(-1.0, min(1.0, net))

        news_cache["headlines"].append({
            "text": title,
            "ticker": ticker,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pos_count": pos,
            "neg_count": neg,
            "net_score": net,
        })
        new_count += 1

    rolling_sent, rolling_pos, rolling_neg, count = compute_rolling_sentiment(entries, ticker)
    penalty = 1.0
    if rolling_sent < 0.0:
        penalty = 1.0 + (rolling_sent * 0.3)
        penalty = max(0.70, penalty)

    if new_count > 0:
        print(f"  [{ticker}] Cached {new_count} new headline(s) | Rolling window: {count} unique articles | Sentiment: {rolling_sent:+.3f}")

    return rolling_sent, penalty, latest_headlines, rolling_pos, rolling_neg, count


def process_ticker(ticker, index, total, news_cache):
    print(f"\n  [{index}/{total}] Processing {ticker} ...")

    stock = yf.Ticker(ticker)

    inc = stock.income_stmt
    if not validate_statement(inc, "Income Statement"):
        print(f"  [{index}/{total}] {ticker} SKIPPED - No income statement data.")
        return None

    bs = stock.balance_sheet
    if not validate_statement(bs, "Balance Sheet"):
        print(f"  [{index}/{total}] {ticker} SKIPPED - No balance sheet data.")
        return None

    if ticker in INSTITUTIONAL_BANKS:
        print(f"  [{index}/{total}] [Sector Notice] Skipping solvency gate for {ticker} due to financial institution banking book structures.")
        print(f"  [{index}/{total}] Assigning baseline neutral safety score (75.0/100).")
        solvency_ok = True
        health_score = 75.0
        cr = None
        dte = None
        directive = f"[MOCK ACTION] Would PASS Solvency (Bank Neutral) and BUY shares."
    else:
        solvency_ok, health_score, cr, dte = evaluate_solvency(bs)
        if solvency_ok is None:
            print(f"  [{index}/{total}] {ticker} SKIPPED - Solvency line items not found.")
            return None
        if not solvency_ok:
            if dte is not None and dte > 1.5:
                directive = f"[MOCK ACTION] Would REJECT due to high leverage (D/E: {dte:.2f})."
                print(f"  [{index}/{total}] [Semantic Analysis]: High leverage indicates this enterprise relies heavily on debt financing, making it highly vulnerable to capital insolvency during contractionary macroeconomic cycles.")
            elif cr is not None and cr < 1.2:
                directive = f"[MOCK ACTION] Would REJECT due to insufficient liquidity (CR: {cr:.2f})."
                print(f"  [{index}/{total}] [Semantic Analysis]: Short-term liquidity bounds are breached, indicating the company mathematically lacks the liquid assets required to satisfy its immediate operational obligations over the next fiscal year.")
            else:
                directive = f"[MOCK ACTION] Would REJECT (CR={cr:.2f}, D/E={dte:.2f})."
        else:
            directive = f"[MOCK ACTION] Would PASS Solvency and BUY shares."

    net_sentiment, penalty, headlines, rolling_pos, rolling_neg, rolling_count = sentiment_gate(stock, ticker, news_cache)

    if solvency_ok and net_sentiment < 0.0:
        print(f"  [{index}/{total}] [Semantic Analysis]: Computational linguistics detect high rhetorical negative sentiment across public news sources, indicating structural headline risk that down-weights our core fundamental asset valuation.")

    adjusted_score = (health_score * penalty) if solvency_ok else health_score
    status = "PASS (Bank Neutral)" if ticker in INSTITUTIONAL_BANKS else ("PASS" if solvency_ok else "FAIL")
    print(f"  [{index}/{total}] {ticker} {status} (Score: {adjusted_score:.1f}/100)")

    return {
        "ticker": ticker,
        "passed": solvency_ok,
        "status": status,
        "directive": directive,
        "health_score": health_score,
        "current_ratio": cr,
        "debt_to_equity": dte,
        "sentiment": net_sentiment,
        "penalty": penalty,
        "adjusted_score": adjusted_score,
        "top_headline": headlines[0] if headlines else "No headlines available.",
        "headlines": headlines,
        "rolling_pos": rolling_pos,
        "rolling_neg": rolling_neg,
        "rolling_count": rolling_count,
    }


def display_portfolio_table(results):
    if not results:
        print(f"\n{'='*80}")
        print(f"  PORTFOLIO DASHBOARD")
        print(f"{'='*80}")
        print(f"  No tickers passed all gates. Portfolio is empty.")
        print(f"{'='*80}")
        return

    ranked = sorted(results, key=lambda x: x["adjusted_score"], reverse=True)
    total_score = sum(r["adjusted_score"] for r in ranked)

    print(f"\n{'='*90}")
    print(f"  PORTFOLIO DASHBOARD — Allocation of ${STARTING_CAPITAL:,}")
    print(f"{'='*90}")
    header = f"  {'Ticker':<8} {'Status':<22} {'Sentiment':>10} {'Alloc %':>10} {'Dollar Amt':>12} {'Shares':>8}"
    print(header)
    print(f"  {'------':<8} {'----------------------':<22} {'----------':>10} {'----------':>10} {'-----------':>12} {'-------':>8}")

    for r in ranked:
        ticker = r["ticker"]
        status = r["status"]
        sent = r["sentiment"]
        score = r["adjusted_score"]
        pct = score / total_score * 100 if total_score > 0 else 0
        dollar_alloc = STARTING_CAPITAL * (pct / 100)

        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.last_price
            if price is None or price <= 0:
                hist = stock.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else 0
        except Exception:
            price = 0

        if price and price > 0:
            target_shares = int(dollar_alloc / price)
        else:
            target_shares = 0

        sent_label = f"{sent:+.3f}"
        print(f"  {ticker:<8} {status:<22} {sent_label:>10} {pct:>9.2f}% ${dollar_alloc:>9,.2f} {target_shares:>7}")

    print(f"  {'------':<8} {'----------------------':<22} {'----------':>10} {'----------':>10} {'-----------':>12} {'-------':>8}")
    print(f"  {'TOTAL':<8} {'':<22} {'':>10} {'100.00%':>10} ${STARTING_CAPITAL:>9,.2f} {'':>7}")
    print(f"{'='*90}")


def check_market_clock():
    eastern = zoneinfo.ZoneInfo("US/Eastern")
    now = datetime.datetime.now(eastern)
    weekday = now.weekday()
    current_time_minutes = now.hour * 60 + now.minute
    open_minutes = 9 * 60 + 30
    close_minutes = 16 * 60
    is_weekday = weekday < 5
    is_market_hours = open_minutes <= current_time_minutes < close_minutes
    if is_weekday and is_market_hours:
        return "MARKET_OPEN", now
    # TEMP OVERRIDE — force MARKET_OPEN for portfolio testing
    return "MARKET_OPEN", now
    # return "ANALYTICAL_OFF_HOURS", now


def load_sandbox_ledger():
    if os.path.exists(SANDBOX_LEDGER):
        with open(SANDBOX_LEDGER, "r") as f:
            return json.load(f)
    return {"cash_balance": STARTING_CAPITAL, "holdings": {}, "history": []}


def save_sandbox_ledger(ledger):
    with open(SANDBOX_LEDGER, "w") as f:
        json.dump(ledger, f, indent=2)


def generate_portfolio_chart(ledger):
    history = ledger.get("history", [])
    if len(history) < 2:
        print(f"\n  {'='*70}")
        print(f"  PORTFOLIO GROWTH CHART")
        print(f"{'='*70}")
        print(f"  Not enough data points to render trend (need 2+ runs).")
        return

    timestamps = [datetime.datetime.fromisoformat(h["timestamp"]) for h in history]
    values = [h["portfolio_value"] for h in history]

    plt.figure(figsize=(12, 6), facecolor='#0d0d1a')
    ax = plt.gca()
    ax.set_facecolor('#1a1a2e')

    ax.plot(timestamps, values, color='#00ff88', linewidth=2.5, label='Net Worth')
    ax.axhline(y=STARTING_CAPITAL, color='#555555', linewidth=1.5, linestyle='--', label=f'Baseline ${STARTING_CAPITAL:,}')

    ax.set_title('Sandbox Portfolio Performance', fontsize=16, fontweight='bold', color='white', pad=15)
    ax.set_xlabel('Time (UTC)', fontsize=12, color='white')
    ax.set_ylabel('Portfolio Value ($)', fontsize=12, color='white')
    ax.legend(loc='upper left', fontsize=11)
    ax.grid(True, alpha=0.3, color='#888888')
    ax.tick_params(colors='white')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.tight_layout()
    plt.savefig('sandbox_performance.png', dpi=150)
    plt.close()

    print(f"  [Chart] sandbox_performance.png saved ({len(history)} data points).")


def sandbox_execute(ranked, total_score):
    ledger = load_sandbox_ledger()
    print(f"\n{'='*80}")
    print(f"  SANDBOX EXECUTION — Auto-Purchasing Passed Tickers")
    print(f"{'='*80}")
    print(f"  Cash Reserve: ${ledger['cash_balance']:,.2f}")
    print(f"  Holdings:     {len(ledger['holdings'])} positions")
    print(f"{'='*80}")

    for r in ranked:
        ticker = r["ticker"]
        score = r["adjusted_score"]
        pct = score / total_score * 100
        dollar_alloc = ledger["cash_balance"] * (pct / 100)

        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.last_price
            if price is None or price <= 0:
                hist = stock.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else 0
        except Exception:
            price = 0

        if price and price > 0:
            target_shares = int(dollar_alloc / price)
            if target_shares > 0:
                cost = target_shares * price
                if ticker in ledger["holdings"]:
                    existing = ledger["holdings"][ticker]
                    total_shares = existing["shares"] + target_shares
                    total_cost = existing["shares"] * existing["avg_price"] + cost
                    existing["shares"] = total_shares
                    existing["avg_price"] = total_cost / total_shares
                else:
                    ledger["holdings"][ticker] = {"shares": target_shares, "avg_price": price}
                ledger["cash_balance"] -= cost
                print(f"  Purchased {target_shares} shares of {ticker} @ ${price:.2f} (${cost:,.2f})")

    total_holdings_value = 0
    for ticker, pos in ledger["holdings"].items():
        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.last_price
            if price is None or price <= 0:
                hist = stock.history(period="1d")
                price = hist["Close"].iloc[-1] if not hist.empty else 0
        except Exception:
            price = 0
        total_holdings_value += pos["shares"] * price

    portfolio_value = ledger["cash_balance"] + total_holdings_value
    ledger["history"].append({
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "portfolio_value": round(portfolio_value, 2),
    })
    save_sandbox_ledger(ledger)

    print(f"\n  Portfolio Value: ${portfolio_value:,.2f}  (Cash: ${ledger['cash_balance']:,.2f} + Holdings: ${total_holdings_value:,.2f})")
    generate_portfolio_chart(ledger)


def handle_reset():
    PIPELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PIPELINE.md")

    if os.path.exists(GATE_FILE):
        os.remove(GATE_FILE)
        gate_status = "deleted"
    else:
        gate_status = "not found"

    if os.path.exists(NEWS_CACHE_FILE):
        os.remove(NEWS_CACHE_FILE)
        cache_status = "deleted"
    else:
        cache_status = "not found"

    if os.path.exists(OBSERVATION_FILE):
        os.remove(OBSERVATION_FILE)
        obs_status = "deleted"
    else:
        obs_status = "not found"

    if os.path.exists(MESSAGE_STATE_FILE):
        with open(MESSAGE_STATE_FILE, "r") as f:
            stored_id = f.read().strip()
        if stored_id:
            webhook_url = os.environ.get("WEBHOOK_URL", "")
            wh_id, wh_token = parse_webhook_parts(webhook_url) if webhook_url else (None, None)
            if wh_id and wh_token:
                try:
                    delete_url = f"https://discord.com/api/webhooks/{wh_id}/{wh_token}/messages/{stored_id}"
                    resp = requests.delete(delete_url, timeout=15)
                    resp.raise_for_status()
                    print(f"\n  [Discord Sync] Active dashboard message ID [{stored_id}] successfully purged from channel history.")
                except Exception as e:
                    print(f"\n  [Discord Sync] Warning: could not purge dashboard message - {e}")
        os.remove(MESSAGE_STATE_FILE)
        msg_status = "deleted"
    else:
        msg_status = "not found"

    if os.path.exists(NEWS_MESSAGE_STATE_FILE):
        with open(NEWS_MESSAGE_STATE_FILE, "r") as f:
            news_stored_id = f.read().strip()
        if news_stored_id:
            webhook_url = os.environ.get("WEBHOOK_URL", "")
            wh_id, wh_token = parse_webhook_parts(webhook_url) if webhook_url else (None, None)
            if wh_id and wh_token:
                try:
                    delete_url = f"https://discord.com/api/webhooks/{wh_id}/{wh_token}/messages/{news_stored_id}"
                    resp = requests.delete(delete_url, timeout=15)
                    resp.raise_for_status()
                    print(f"\n  [Discord Sync] News roundup message ID [{news_stored_id}] successfully purged from channel history.")
                except Exception as e:
                    print(f"\n  [Discord Sync] Warning: could not purge news roundup message - {e}")
        os.remove(NEWS_MESSAGE_STATE_FILE)
        news_msg_status = "deleted"
    else:
        news_msg_status = "not found"

    if os.path.exists(PIPELINE_PATH):
        with open(PIPELINE_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        divider_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]
        if len(divider_indices) >= 2:
            keep_start = divider_indices[0] + 1
            keep_end = divider_indices[-1]
            new_lines = lines[:keep_start] + lines[keep_end:]
        else:
            new_lines = lines
        cleaned = [new_lines[0]]
        for line in new_lines[1:]:
            if line.strip() == "---" and cleaned[-1].strip() == "---":
                continue
            cleaned.append(line)
        with open(PIPELINE_PATH, "w", encoding="utf-8") as f:
            f.writelines(cleaned)
        pipeline_status = "log entries cleared"
    else:
        pipeline_status = "not found"

    print(f"\n{'='*80}")
    print(f"  SYSTEM RESET")
    print(f"{'='*80}")
    print(f"  .last_run:           {gate_status}")
    print(f"  .news_cache.json:    {cache_status}")
    print(f"  .observation_state:  {obs_status}")
    print(f"  .message_state:      {msg_status}")
    print(f"  .news_message_state: {news_msg_status}")
    print(f"  PIPELINE.md:         {pipeline_status}")
    print(f"  System reset complete. Ready for new epoch.")
    print(f"{'='*80}")
    sys.exit(0)


def parse_args_and_mode():
    parser = argparse.ArgumentParser(
        description="Glassbox Finance — Wolves of Wall Street",
        add_help=True
    )
    parser.add_argument("--sandbox", action="store_true",
                        help="Run in SANDBOX mode (twin-clock paper trading with 1-min visualization)")
    parser.add_argument("--comp", action="store_true",
                        help="Run in COMPETITION mode (strict 24h advisory routing desk)")
    parser.add_argument("--clear", action="store_true",
                        help="System reset and infrastructure purge")

    args = parser.parse_args()

    if args.clear:
        handle_reset()

    if args.sandbox and args.comp:
        print("  Error: --sandbox and --comp are mutually exclusive.")
        sys.exit(1)

    if args.sandbox:
        return "SANDBOX"

    if args.comp:
        return "COMPETITION"

    print("\n  Glassbox Finance — Wolves of Wall Street")
    print("  " + "-" * 50)
    print("  Usage: python main.py [--sandbox | --comp | --clear]")
    print()
    print("  --sandbox   Run paper trading with real-time 1-min visualization")
    print("  --comp      Run competition advisory desk with 24h routing rules  (default)")
    print("  --clear     Purge all local state, caches, and Discord dashboard")
    print("  " + "-" * 50 + "\n")
    return "COMPETITION"


def main():
    RUN_MODE = parse_args_and_mode()

    print(f"\n{'='*80}")
    print(f"  GLASSBOX FINANCE — Twin-Clock Architecture")
    print(f"  Mode: {RUN_MODE}  |  Universe: {len(TICKERS)} tickers")
    print(f"{'='*80}")

    news_cache = load_news_cache()

    while True:
        cycle_start = datetime.datetime.now(datetime.timezone.utc)

        pruned, window_hours = prune_news_cache(news_cache)
        if pruned > 0:
            print(f"  [Cache] Pruned {pruned} headline(s) older than {window_hours}h window.")

        market_state, et_now = check_market_clock()

        if RUN_MODE == "COMPETITION":
            daily_allowed = check_daily_gate()
            if daily_allowed and market_state == "MARKET_OPEN":
                news_alerts = []
                passed_results = []
                for i, ticker in enumerate(TICKERS, start=1):
                    try:
                        result = process_ticker(ticker, i, len(TICKERS), news_cache)
                        if result is not None:
                            news_alerts.append(result)
                            if result["passed"]:
                                passed_results.append(result)
                    except Exception as e:
                        print(f"  [{i}/{len(TICKERS)}] {ticker} ERROR - {e}")
                save_news_cache(news_cache)
                send_batched_news(news_alerts, et_now)
                display_portfolio_table(passed_results)
                send_master_report(passed_results, market_state, et_now, len(TICKERS))
                mark_daily_allocation()
                print(f"  [Gate] Daily allocation executed and timestamped.")
            else:
                if not daily_allowed:
                    print(f"  [Gate] 24h cooldown active — skipped.")
                if market_state != "MARKET_OPEN":
                    print(f"  [Gate] Outside NYSE hours — skipped.")
            print(f"\n  Next cycle +{LOOP_INTERVAL_MINUTES}min.")
            time.sleep(LOOP_INTERVAL_MINUTES * 60)
            continue

        # === SANDBOX TWIN-CLOCK ===
        if market_state != "MARKET_OPEN":
            print(f"  [Clock] Market closed — 60min standby.")
            print(f"  {'='*80}")
            time.sleep(LOOP_INTERVAL_MINUTES * 60)
            continue

        daily_allowed = check_daily_gate()
        obs_state = load_observation_state()
        clock_label = obs_state.get("clock_state", "LOCKED")

        print(f"\n  [{cycle_start.strftime('%H:%M UTC')}] MARKET_OPEN  |  24-Hour Gate: {'EXPIRED' if daily_allowed else 'LOCKED'}  |  Observation Clock: {clock_label}")
        print(f"  {'='*80}")

        if daily_allowed and clock_label == "LOCKED":
            obs_state["clock_state"] = "OBSERVING"
            obs_state["observation_start"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            obs_state["price_log"] = {}
            save_observation_state(obs_state)
            collect_spot_prices(obs_state, TICKERS)
            save_observation_state(obs_state)
            ledger = visualization_update()
            payload = build_sandbox_status(ledger, "OBSERVING INTRA-DAY VOLATILITY", et_now)
            send_or_update_dashboard(payload, image_path="sandbox_performance.png" if os.path.exists("sandbox_performance.png") else None)
            print(f"  [Smart Trigger] Entering observation state — collecting volatility data.")

        elif clock_label == "OBSERVING":
            collect_spot_prices(obs_state, TICKERS)
            save_observation_state(obs_state)
            if volatility_stabilized(obs_state):
                print(f"  [Smart Trigger]: Market volatility stabilized. Executing daily portfolio rebalance and locking decision gate for 24 hours.")
                news_alerts = []
                passed_results = []
                for i, ticker in enumerate(TICKERS, start=1):
                    try:
                        result = process_ticker(ticker, i, len(TICKERS), news_cache)
                        if result is not None:
                            news_alerts.append(result)
                            if result["passed"]:
                                passed_results.append(result)
                    except Exception as e:
                        print(f"  [{i}/{len(TICKERS)}] {ticker} ERROR - {e}")
                save_news_cache(news_cache)
                send_batched_news(news_alerts, et_now)
                ranked = sorted(passed_results, key=lambda x: x["adjusted_score"], reverse=True)
                total_score = sum(r["adjusted_score"] for r in ranked) if ranked else 1
                sandbox_execute(ranked, total_score)
                mark_daily_allocation()
                obs_state["clock_state"] = "LOCKED"
                obs_state["price_log"] = {}
                save_observation_state(obs_state)
                ledger = load_sandbox_ledger()
                payload = build_master_payload(passed_results, market_state, et_now, len(TICKERS), clock_state="LOCKED")
                send_or_update_dashboard(payload, image_path="sandbox_performance.png")
            else:
                ledger = visualization_update()
                spread = compute_volatility_spread(obs_state.get("price_log", {}))
                print(f"  [Volatility] Current spread: {spread:.6f}  |  Threshold: {VOLATILITY_THRESHOLD}  |  Waiting for stabilization.")
                payload = build_sandbox_status(ledger, "OBSERVING INTRA-DAY VOLATILITY", et_now)
                send_or_update_dashboard(payload, image_path="sandbox_performance.png" if os.path.exists("sandbox_performance.png") else None)

        else:
            ledger = visualization_update()
            payload = build_sandbox_status(ledger, "UPDATING REAL-TIME VALUE", et_now)
            send_or_update_dashboard(payload, image_path="sandbox_performance.png" if os.path.exists("sandbox_performance.png") else None)

        print(f"  [Next] +60s.")
        print(f"  {'='*80}")
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{'=' * 80}")
        print(f"                             ENGINE SYSTEM TERMINATED")
        print(f"{'=' * 80}")
        print(f"  [System]: Background tracking scrawler loops successfully suspended by user.")
        print(f"  [Status]: Core operational data cache and local state files preserved safely.")
        print(f"{'=' * 80}")
        sys.exit(0)
