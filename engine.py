import os
import math
import json
import time
import datetime
import re
import random
import threading
import zoneinfo
import requests
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config import *


# ── helpers ──────────────────────────────────────────────────────────────

def load_news_cache():
    if os.path.exists(NEWS_CACHE_FILE):
        with open(NEWS_CACHE_FILE, "r") as f:
            return json.load(f)
    return {"headlines": []}


def save_news_cache(cache):
    with open(NEWS_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def get_cache_window_hours():
    weekday = datetime.datetime.now(datetime.timezone.utc).weekday()
    if weekday in (1, 2, 3):  # Tue–Thu
        return 24
    return 72  # Fri–Mon


def prune_news_cache(cache):
    window_hours = get_cache_window_hours()
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


def compute_rolling_sentiment(entries, ticker, window_hours=None):
    if window_hours is None:
        window_hours = get_cache_window_hours()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=window_hours)
    now = datetime.datetime.now(datetime.timezone.utc)
    ticker_entries = [
        h for h in entries
        if h["ticker"] == ticker
        and datetime.datetime.fromisoformat(h["timestamp"]) >= cutoff
    ]
    if not ticker_entries:
        return 0.0, 0, 0, 0
    total_weight = 0.0
    weighted_net = 0.0
    weighted_pos = 0.0
    weighted_neg = 0.0
    for h in ticker_entries:
        age = now - datetime.datetime.fromisoformat(h["timestamp"])
        age_hours = age.total_seconds() / 3600
        weight = 0.5 ** (age_hours / DECAY_HALF_LIFE_HOURS)
        total_weight += weight
        weighted_net += h["net_score"] * weight
        weighted_pos += h["pos_count"] * weight
        weighted_neg += h["neg_count"] * weight
    avg_net = weighted_net / total_weight if total_weight > 0 else 0.0
    return avg_net, round(weighted_pos), round(weighted_neg), len(ticker_entries)


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


def load_observation_state():
    if os.path.exists(OBSERVATION_FILE):
        with open(OBSERVATION_FILE, "r") as f:
            return json.load(f)
    return {"clock_state": "LOCKED", "observation_start": None, "price_log": {}}


def save_observation_state(state):
    with open(OBSERVATION_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── market helpers ────────────────────────────────────────────────────────

def check_market_clock():
    eastern = zoneinfo.ZoneInfo("US/Eastern")
    now = datetime.datetime.now(eastern)
    weekday = now.weekday()
    current_time_minutes = now.hour * 60 + now.minute
    open_minutes = 9 * 60 + 30
    close_minutes = 16 * 60
    if weekday < 5 and open_minutes <= current_time_minutes < close_minutes:
        return "MARKET_OPEN", now
    return "ANALYTICAL_OFF_HOURS", now


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


# ── news cycle helpers ────────────────────────────────────────────────────

def check_news_cycle():
    if not os.path.exists(NEWS_CYCLE_FILE):
        return True
    with open(NEWS_CYCLE_FILE, "r") as f:
        stored = f.read().strip()
    try:
        last_run = datetime.datetime.fromisoformat(stored)
    except ValueError:
        return True
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=datetime.timezone.utc)
    elapsed = datetime.datetime.now(datetime.timezone.utc) - last_run
    return elapsed >= datetime.timedelta(hours=NEWS_CYCLE_HOURS)


def mark_news_cycle():
    with open(NEWS_CYCLE_FILE, "w") as f:
        f.write(datetime.datetime.now(datetime.timezone.utc).isoformat())


def acquire_news_lock():
    for attempt in range(5):
        if not os.path.exists(NEWS_LOCK_FILE):
            with open(NEWS_LOCK_FILE, "w") as f:
                f.write(datetime.datetime.now(datetime.timezone.utc).isoformat())
            return True
        print(f"  [News] Lock held — retrying ({attempt + 1}/5)...")
        time.sleep(1)
    print("  [News] Could not acquire lock.")
    return False


def release_news_lock():
    if os.path.exists(NEWS_LOCK_FILE):
        os.remove(NEWS_LOCK_FILE)


# ── sandbox helpers ───────────────────────────────────────────────────────

def load_sandbox_ledger():
    if os.path.exists(SANDBOX_LEDGER):
        with open(SANDBOX_LEDGER, "r") as f:
            return json.load(f)
    return {"cash_balance": STARTING_CAPITAL, "holdings": {}, "history": []}


def save_sandbox_ledger(ledger):
    with open(SANDBOX_LEDGER, "w") as f:
        json.dump(ledger, f, indent=2)


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


# ── webhook helpers ──────────────────────────────────────────────────────

def parse_webhook_parts(url):
    base = url.split("?")[0].rstrip("/")
    parts = base.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, None


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


def send_batched_news(alerts, et_now):
    if not alerts:
        return
    payload = build_news_roundup(alerts, et_now)
    MAX_MSG = 1997
    if len(payload) > MAX_MSG:
        cutoff = payload.rfind("\n", 0, MAX_MSG - 3)
        if cutoff < 0:
            cutoff = MAX_MSG - 3
        payload = payload[:cutoff] + "\n... truncated"
    print(f"\n  [News Roundup] Payload: {len(payload)} chars, {len(alerts)} tickers.")
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
        try:
            resp_text = e.response.text[:500] if e.response is not None else ""
            if resp_text:
                print(f"  [News Roundup] Response: {resp_text}")
        except Exception:
            pass


# ── news flash ────────────────────────────────────────────────────────────

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


# ── summarizers / builders ───────────────────────────────────────────────

def summarize_news_entry(ticker, headlines, rolling_sent, rolling_pos, rolling_neg, rolling_count, long_sent=None):
    if not headlines:
        base = f"{ticker} [{rolling_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> No headlines."
        if long_sent is not None:
            base = f"{ticker} [{rolling_sent:+.2f} / {long_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> No headlines."
        return base
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
    if long_sent is not None:
        return f"{ticker} [{rolling_sent:+.2f} / {long_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> {best_h}"
    return f"{ticker} [{rolling_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> {best_h}"


def build_news_roundup(alerts, et_now):
    lines = []
    lines.append("=" * 80)
    lines.append("                         GLASSBOX NEWS ROUNDUP")
    lines.append(f"  Scanner: {WATCHLIST_SCANNER_LIMIT} tickers  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append("=" * 80)
    for r in alerts:
        row = summarize_news_entry(
            r["ticker"], r.get("headlines", []),
            r["sentiment"], r["rolling_pos"], r["rolling_neg"], r["rolling_count"],
            long_sent=r.get("long_sentiment")
        )
        lines.append(f"  {row}")
    lines.append("=" * 80)
    lines.append(f"  {len(alerts)} headlines  |  24h Rolling Window  |  7d Trend Anchor")
    lines.append("=" * 80)
    return "\n".join(lines)


def build_master_payload(results, market_state, et_now, total_tickers, clock_state=None):
    ranked = sorted(results, key=lambda x: x["adjusted_score"], reverse=True)
    top = ranked[:MAX_PORTFOLIO_HOLDINGS]
    total_score = sum(r["adjusted_score"] for r in top) if top else 1
    n_passing = len(ranked)
    n_holding = len(top)
    lines = []
    lines.append("**Glassbox Finance - MASTER EXECUTION REPORT**")
    if clock_state:
        lines.append(f"Status: {market_state} — Clock: {clock_state}  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    else:
        lines.append(f"Status: {market_state}  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"Scanner: {WATCHLIST_SCANNER_LIMIT} tickers | Passed: {n_passing} | Funded: {n_holding}")
    lines.append(f"Capital: ${STARTING_CAPITAL:,}")
    lines.append("")
    lines.append("```")
    header = f"{'Ticker':<8} {'Status':<22} {'Sentiment':>10} {'Alloc %':>10} {'$ Amt':>12} {'Shares':>8}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in top:
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


def build_sandbox_status(ledger, clock_state, et_now):
    pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL
    change = pv - STARTING_CAPITAL
    pct = (change / STARTING_CAPITAL) * 100
    arrow = "+" if change >= 0 else ""
    lines = []
    lines.append(f"**Glassbox Finance — SANDBOX DASHBOARD**")
    lines.append(f"Status: MARKET_OPEN — Clock: {clock_state}  |  {et_now.strftime('%H:%M UTC')}")
    lines.append(f"Scanner: {WATCHLIST_SCANNER_LIMIT} tickers | Holdings: {len(ledger['holdings'])} / {MAX_PORTFOLIO_HOLDINGS}")
    lines.append(f"Portfolio: ${pv:,.2f}  ({arrow}{change:,.2f} / {arrow}{pct:.2f}%)")
    lines.append(f"Cash: ${ledger['cash_balance']:,.2f}")
    last = ledger["history"][-1] if ledger["history"] else {}
    if last.get("realized_pnl"):
        rp = last["realized_pnl"]
        rp_arrow = "+" if rp >= 0 else ""
        lines.append(f"Realized P&L: {rp_arrow}${rp:,.2f}")
    return "\n".join(lines)


def send_master_report(results, market_state, et_now, total_tickers, image_path=None):
    payload = build_master_payload(results, market_state, et_now, total_tickers)
    send_webhook_payload(payload, "Master Execution Report", image_path=image_path)


# ── validation ────────────────────────────────────────────────────────────

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


# ── sentiment ─────────────────────────────────────────────────────────────

def sentiment_gate(stock, ticker, news_cache, skip_fetch=False):
    entries = news_cache["headlines"]
    if skip_fetch:
        short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
        long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
        blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
        penalty = 1.0
        if blended < 0.0:
            penalty = 1.0 + (blended * 0.3)
            penalty = max(0.70, penalty)
        return short_sent, penalty, [], short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count
    try:
        news_raw = stock.news
    except Exception:
        short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
        long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
        blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
        penalty = 1.0
        if blended < 0.0:
            penalty = 1.0 + (blended * 0.3)
            penalty = max(0.70, penalty)
        return short_sent, penalty, [], short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count
    if not news_raw:
        short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
        long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
        blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
        penalty = 1.0
        if blended < 0.0:
            penalty = 1.0 + (blended * 0.3)
            penalty = max(0.70, penalty)
        return short_sent, penalty, [], short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count
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
    short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
    long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
    blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
    penalty = 1.0
    if blended < 0.0:
        penalty = 1.0 + (blended * 0.3)
        penalty = max(0.70, penalty)
    if new_count > 0:
        print(f"  [{ticker}] Cached {new_count} new headline(s) | Short: {short_sent:+.3f} | 7d: {long_sent:+.3f} | Blended: {blended:+.3f}")
    return short_sent, penalty, latest_headlines, short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count


# ── ticker processing ────────────────────────────────────────────────────

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
    net_sentiment, penalty, headlines, rolling_pos, rolling_neg, rolling_count, long_sent, long_pos, long_neg, long_count = sentiment_gate(stock, ticker, news_cache, skip_fetch=True)
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
        "long_sentiment": long_sent,
        "long_rolling_pos": long_pos,
        "long_rolling_neg": long_neg,
        "long_rolling_count": long_count,
    }


# ── display ──────────────────────────────────────────────────────────────

def display_portfolio_table(results):
    if not results:
        print(f"\n{'='*80}")
        print(f"  PORTFOLIO DASHBOARD")
        print(f"{'='*80}")
        print(f"  No tickers passed all gates. Portfolio is empty.")
        print(f"  [Scanner] {WATCHLIST_SCANNER_LIMIT} tickers evaluated, 0 passed.")
        print(f"{'='*80}")
        return
    ranked = sorted(results, key=lambda x: x["adjusted_score"], reverse=True)
    top = ranked[:MAX_PORTFOLIO_HOLDINGS]
    n_passing = len(ranked)
    n_holding = len(top)
    total_score = sum(r["adjusted_score"] for r in top)
    print(f"\n{'='*90}")
    print(f"  PORTFOLIO DASHBOARD — Allocation of ${STARTING_CAPITAL:,}")
    print(f"  [Scanner] {WATCHLIST_SCANNER_LIMIT} evaluated | {n_passing} passed | Top {n_holding} funded")
    print(f"{'='*90}")
    header = f"  {'Ticker':<8} {'Status':<22} {'Sentiment':>10} {'Alloc %':>10} {'$ Amt':>12} {'Shares':>8}"
    print(header)
    print(f"  {'------':<8} {'----------------------':<22} {'----------':>10} {'----------':>10} {'-----------':>12} {'-------':>8}")
    for r in top:
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


# ── visualization ────────────────────────────────────────────────────────

def visualization_update():
    ledger = load_sandbox_ledger()
    total_holdings_value = 0
    for ticker, pos in ledger["holdings"].items():
        price = _get_price(ticker)
        total_holdings_value += pos["shares"] * price
    portfolio_value = ledger["cash_balance"] + total_holdings_value
    ledger["history"].append({
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "portfolio_value": round(portfolio_value, 2),
    })
    save_sandbox_ledger(ledger)
    generate_portfolio_chart(ledger)
    return ledger


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
    plt.savefig(SANDBOX_CHART, dpi=150)
    plt.close()
    print(f"  [Chart] {SANDBOX_CHART} saved ({len(history)} data points).")


def _get_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.last_price
        if price is None or price <= 0:
            hist = stock.history(period="1d")
            price = hist["Close"].iloc[-1] if not hist.empty else 0
        return price
    except Exception:
        return 0


def sandbox_execute(ranked, total_score):
    ledger = load_sandbox_ledger()
    new_tickers = {r["ticker"] for r in ranked}

    print(f"\n{'='*80}")
    print(f"  SANDBOX EXECUTION — Portfolio Rebalance (Sell / Hold / Buy)")
    print(f"{'='*80}")
    print(f"  Cash:           ${ledger['cash_balance']:>10,.2f}")
    print(f"  Current Holdings: {len(ledger['holdings'])} positions")
    print(f"{'='*80}")

    realized_pnl = 0.0

    # Phase 1: SELL — exit held positions not in new allocation
    for ticker in list(ledger["holdings"].keys()):
        if ticker in new_tickers:
            continue
        pos = ledger["holdings"][ticker]
        price = _get_price(ticker)
        if price and price > 0:
            proceeds = pos["shares"] * price
            cost_basis = pos["shares"] * pos["avg_price"]
            pnl = proceeds - cost_basis
            realized_pnl += pnl
            ledger["cash_balance"] += proceeds
            del ledger["holdings"][ticker]
            print(f"  SELL  {pos['shares']} shares of {ticker} @ ${price:.2f}  (P&L: ${pnl:+,.2f})")
        else:
            print(f"  SELL  {pos['shares']} shares of {ticker} @ price N/A — skipped.")

    # Phase 2: HOLD — report existing positions that stay
    for ticker in sorted(new_tickers):
        if ticker in ledger["holdings"]:
            pos = ledger["holdings"][ticker]
            price = _get_price(ticker)
            val = pos["shares"] * price if price else 0
            print(f"  HOLD  {pos['shares']} shares of {ticker} @ ${price:.2f}  (Value: ${val:,.2f})")

    # Phase 3: BUY — new positions only
    buy_targets = [r for r in ranked if r["ticker"] not in ledger["holdings"]]
    buy_total_score = sum(r["adjusted_score"] for r in buy_targets) or 1
    for r in buy_targets:
        ticker = r["ticker"]
        pct = r["adjusted_score"] / buy_total_score * 100
        dollar_alloc = ledger["cash_balance"] * (pct / 100)
        price = _get_price(ticker)
        if price and price > 0:
            target_shares = int(dollar_alloc / price)
            if target_shares > 0:
                cost = target_shares * price
                ledger["holdings"][ticker] = {"shares": target_shares, "avg_price": price}
                ledger["cash_balance"] -= cost
                print(f"  BUY   {target_shares} shares of {ticker} @ ${price:.2f}  (${cost:,.2f})")

    # Valuate
    total_holdings_value = 0
    for ticker, pos in ledger["holdings"].items():
        price = _get_price(ticker)
        total_holdings_value += pos["shares"] * (price if price else 0)

    portfolio_value = ledger["cash_balance"] + total_holdings_value
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "portfolio_value": round(portfolio_value, 2),
    }
    if realized_pnl != 0:
        entry["realized_pnl"] = round(realized_pnl, 2)
    ledger["history"].append(entry)
    save_sandbox_ledger(ledger)

    print(f"\n  Portfolio Summary:")
    print(f"  Cash:      ${ledger['cash_balance']:>10,.2f}")
    print(f"  Holdings:  ${total_holdings_value:>10,.2f}")
    print(f"  Total:     ${portfolio_value:>10,.2f}")
    if realized_pnl != 0:
        print(f"  Realized:  ${realized_pnl:>+10,.2f}")
    generate_portfolio_chart(ledger)


# ── reset ────────────────────────────────────────────────────────────────

def handle_reset():
    state_files = [
        GATE_FILE, NEWS_CACHE_FILE, OBSERVATION_FILE,
        MESSAGE_STATE_FILE, NEWS_MESSAGE_STATE_FILE,
        NEWS_CYCLE_FILE, NEWS_LOCK_FILE
    ]
    statuses = {}
    for path in state_files:
        name = os.path.basename(path)
        if os.path.exists(path):
            if name in (os.path.basename(MESSAGE_STATE_FILE), os.path.basename(NEWS_MESSAGE_STATE_FILE)):
                stored_id = ""
                with open(path, "r") as f:
                    stored_id = f.read().strip()
                if stored_id:
                    webhook_url = os.environ.get("WEBHOOK_URL", "")
                    wh_id, wh_token = parse_webhook_parts(webhook_url) if webhook_url else (None, None)
                    if wh_id and wh_token:
                        try:
                            delete_url = f"https://discord.com/api/webhooks/{wh_id}/{wh_token}/messages/{stored_id}"
                            resp = requests.delete(delete_url, timeout=15)
                            resp.raise_for_status()
                            print(f"\n  [Discord Sync] Message ID [{stored_id}] purged from channel history.")
                        except Exception as ex:
                            print(f"\n  [Discord Sync] Warning: could not purge message - {ex}")
            os.remove(path)
            statuses[name] = "deleted"
        else:
            statuses[name] = "not found"
    PIPELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PIPELINE.md")
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
    for name, st in statuses.items():
        print(f"  {name:<25} {st}")
    print(f"  PIPELINE.md{'':<15} {pipeline_status}")
    print(f"  System reset complete. Ready for new epoch.")
    print(f"{'='*80}")


# ── news stream ──────────────────────────────────────────────────────────

def run_news_stream(news_cache, et_now):
    news_alerts = []
    total = len(TICKERS)
    for i, ticker in enumerate(TICKERS, start=1):
        try:
            stock = yf.Ticker(ticker)
            sent, penalty, headlines, sp, sn, sc, ls, lp, ln, lc = sentiment_gate(stock, ticker, news_cache)
            news_alerts.append({
                "ticker": ticker,
                "headlines": headlines,
                "sentiment": sent,
                "rolling_pos": sp,
                "rolling_neg": sn,
                "rolling_count": sc,
                "long_sentiment": ls,
                "long_rolling_pos": lp,
                "long_rolling_neg": ln,
                "long_rolling_count": lc,
            })
            if headlines:
                print(f"  [News] {ticker} ({i}/{total}) — {len(headlines)} new | Short: {sent:+.3f} | 7d: {ls:+.3f}")
        except Exception as e:
            print(f"  [News] {ticker} ({i}/{total}) ERROR — {e}")
        if i < total:
            time.sleep(random.uniform(NEWS_RATE_MIN, NEWS_RATE_MAX))
    save_news_cache(news_cache)
    send_batched_news(news_alerts, et_now)
    print(f"  [News] Stream complete — {len(news_alerts)} tickers. Next cycle +60min.")


# ── Engine Runner ────────────────────────────────────────────────────────

class EngineRunner:
    def __init__(self, run_mode="COMPETITION"):
        self.run_mode = run_mode
        self._paused = threading.Event()
        self._paused.set()
        self._stopped = threading.Event()
        self._trigger = threading.Event()
        self._thread = None
        self.status = {
            "mode": run_mode,
            "clock_state": "LOCKED",
            "market_state": "ANALYTICAL_OFF_HOURS",
            "last_run_utc": None,
            "uptime_start_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "paused": False,
            "news_last_run": None,
            "holdings_count": 0,
            "portfolio_value": STARTING_CAPITAL,
        }
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="Engine")
        self._thread.start()

    def stop(self):
        self._stopped.set()
        self._paused.set()

    def pause(self):
        self._paused.clear()
        with self._lock:
            self.status["paused"] = True

    def resume(self):
        self._paused.set()
        with self._lock:
            self.status["paused"] = False

    def trigger_now(self):
        self._trigger.set()
        self._paused.set()

    def clear_trigger(self):
        self._trigger.clear()

    def switch_mode(self, mode):
        self.run_mode = mode
        with self._lock:
            self.status["mode"] = mode

    def _sleep_with_trigger(self, seconds):
        interval = 5
        elapsed = 0
        while elapsed < seconds and not self._stopped.is_set():
            if self._trigger.is_set():
                return
            time.sleep(min(interval, seconds - elapsed))
            elapsed += interval

    def get_status(self):
        with self._lock:
            return dict(self.status)

    def _update_status(self, **kw):
        with self._lock:
            self.status.update(kw)

    def _run_loop(self):
        print(f"\n{'='*80}")
        print(f"  GLASSBOX FINANCE — Three-Clock Architecture")
        print(f"  Mode: {self.run_mode}  |  Watchlist: {WATCHLIST_SCANNER_LIMIT} tickers  |  Max Holdings: {MAX_PORTFOLIO_HOLDINGS}")
        print(f"{'='*80}")

        news_cache = load_news_cache()
        release_news_lock()

        while not self._stopped.is_set():
            self._paused.wait()

            cycle_start = datetime.datetime.now(datetime.timezone.utc)

            pruned, window_hours = prune_news_cache(news_cache)
            if pruned > 0:
                print(f"  [Cache] Pruned {pruned} headline(s) older than {window_hours}h window.")

            market_state, et_now = check_market_clock()
            self._update_status(market_state=market_state)

            if check_news_cycle():
                if acquire_news_lock():
                    try:
                        run_news_stream(news_cache, et_now)
                        mark_news_cycle()
                        self._update_status(news_last_run=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    finally:
                        release_news_lock()

            if self.run_mode == "COMPETITION":
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
                    clipped = sorted(passed_results, key=lambda x: x["adjusted_score"], reverse=True)[:MAX_PORTFOLIO_HOLDINGS]
                    display_portfolio_table(clipped)
                    send_master_report(clipped, market_state, et_now, len(TICKERS))
                    mark_daily_allocation()
                    self._update_status(last_run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    print(f"  [Gate] Daily allocation executed and timestamped.")
                else:
                    if not daily_allowed:
                        print(f"  [Gate] 24h cooldown active — skipped.")
                    if market_state != "MARKET_OPEN":
                        print(f"  [Gate] Outside NYSE hours — skipped.")
                print(f"\n  Next cycle +{LOOP_INTERVAL_MINUTES}min.")
                self._sleep_with_trigger(LOOP_INTERVAL_MINUTES * 60)
                self.clear_trigger()
                continue

            if market_state != "MARKET_OPEN":
                print(f"  [Clock] Market closed — 60min standby.")
                print(f"  {'='*80}")
                self._sleep_with_trigger(LOOP_INTERVAL_MINUTES * 60)
                self.clear_trigger()
                continue

            daily_allowed = check_daily_gate()
            obs_state = load_observation_state()
            clock_label = obs_state.get("clock_state", "LOCKED")
            self._update_status(clock_state=clock_label)

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
                self._update_status(clock_state="OBSERVING", holdings_count=len(ledger["holdings"]), portfolio_value=ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL)
                payload = build_sandbox_status(ledger, "OBSERVING INTRA-DAY VOLATILITY", et_now)
                send_or_update_dashboard(payload, image_path=SANDBOX_CHART if os.path.exists(SANDBOX_CHART) else None)
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
                    clipped = sorted(passed_results, key=lambda x: x["adjusted_score"], reverse=True)[:MAX_PORTFOLIO_HOLDINGS]
                    total_score = sum(r["adjusted_score"] for r in clipped) if clipped else 1
                    sandbox_execute(clipped, total_score)
                    mark_daily_allocation()
                    obs_state["clock_state"] = "LOCKED"
                    obs_state["price_log"] = {}
                    save_observation_state(obs_state)
                    ledger = load_sandbox_ledger()
                    self._update_status(clock_state="LOCKED", last_run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), holdings_count=len(ledger["holdings"]), portfolio_value=ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL)
                    payload = build_master_payload(clipped, market_state, et_now, len(TICKERS), clock_state="LOCKED")
                    send_or_update_dashboard(payload, image_path=SANDBOX_CHART)
                else:
                    ledger = visualization_update()
                    spread = compute_volatility_spread(obs_state.get("price_log", {}))
                    print(f"  [Volatility] Current spread: {spread:.6f}  |  Threshold: {VOLATILITY_THRESHOLD}  |  Waiting for stabilization.")
                    payload = build_sandbox_status(ledger, "OBSERVING INTRA-DAY VOLATILITY", et_now)
                    send_or_update_dashboard(payload, image_path=SANDBOX_CHART if os.path.exists(SANDBOX_CHART) else None)
            else:
                ledger = visualization_update()
                self._update_status(holdings_count=len(ledger["holdings"]), portfolio_value=ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL)
                payload = build_sandbox_status(ledger, "UPDATING REAL-TIME VALUE", et_now)
                send_or_update_dashboard(payload, image_path=SANDBOX_CHART if os.path.exists(SANDBOX_CHART) else None)

            print(f"  [Next] +60s.")
            print(f"  {'='*80}")
            self._sleep_with_trigger(60)
            self.clear_trigger()
