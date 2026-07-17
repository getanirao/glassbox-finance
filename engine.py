import os
import math
import json
import time
import datetime
import re
import random
import threading
import shutil
import zoneinfo
import requests
import logging
_yf_logger = logging.getLogger('yfinance')
_yf_logger.disabled = True
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config import *

from sentiment import score_headline, get_scorer

NEWS_LOCK_OWNER = f"{os.getpid()}:{datetime.datetime.now(datetime.timezone.utc).isoformat()}"


# ── helpers ──────────────────────────────────────────────────────────────

def load_news_cache():
    if os.path.exists(NEWS_CACHE_FILE):
        with open(NEWS_CACHE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and "headlines" in data:
            tickers_seen = set(h.get("ticker") for h in data["headlines"])
            if len(tickers_seen) < 3 and os.path.exists(NEWS_CACHE_BACKUP):
                print(f"  [Cache] Main cache has only {len(tickers_seen)} ticker(s); restoring from backup.")
                with open(NEWS_CACHE_BACKUP, "r") as f:
                    data = json.load(f)
        return data
    if os.path.exists(NEWS_CACHE_BACKUP):
        print(f"  [Cache] Main cache missing; restoring from backup.")
        with open(NEWS_CACHE_BACKUP, "r") as f:
            return json.load(f)
    return {"headlines": []}


def save_news_cache(cache):
    if isinstance(cache, dict) and "headlines" in cache:
        tickers_seen = set(h.get("ticker") for h in cache["headlines"])
        if len(tickers_seen) >= len(TICKERS) * 0.5:
            if os.path.exists(NEWS_CACHE_FILE):
                shutil.copy2(NEWS_CACHE_FILE, NEWS_CACHE_BACKUP)
    with open(NEWS_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def repair_news_cache(cache):
    fixed = 0
    for h in cache["headlines"]:
        text = h.get("text", "")
        net, pos, neg = score_headline(text)
        old_net = h.get("net_score", 0)
        if abs(old_net - net) > 0.001:
            h["net_score"] = round(net, 4)
            h["pos_count"] = round(pos, 4)
            h["neg_count"] = round(neg, 4)
            h["critical_neg"] = 0
            fixed += 1
    if fixed:
        print(f"  [Cache] Repaired {fixed} headline(s) with FinBERT scores.")
    return fixed


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
    name = TICKER_NAMES.get(ticker, "").lower()
    total_weight = 0.0
    weighted_net = 0.0
    weighted_pos = 0.0
    weighted_neg = 0.0
    for h in ticker_entries:
        age = now - datetime.datetime.fromisoformat(h["timestamp"])
        age_hours = age.total_seconds() / 3600
        weight = 0.5 ** (age_hours / DECAY_HALF_LIFE_HOURS)
        hl = h["text"].lower()
        relevance = 1.0
        if ticker.lower() in hl:
            relevance = 3.0
        elif name and any(w in hl for w in name.split()):
            relevance = 2.0
        else:
            relevance = 0.33
        weight *= relevance
        net_score = h["net_score"]
        if net_score < 0 and relevance >= 1.0:
            weight *= 1 + (abs(net_score) * DOWNSIDE_SENTIMENT_WEIGHT)
        critical = h.get("critical_neg", 0)
        if critical > 0:
            weight *= (1 + critical)
        total_weight += weight
        weighted_net += net_score * weight
        weighted_pos += h["pos_count"] * weight
        weighted_neg += h["neg_count"] * weight
    avg_net = weighted_net / total_weight if total_weight > 0 else 0.0
    return avg_net, round(weighted_pos), round(weighted_neg), len(ticker_entries)


# ── message state helpers ────────────────────────────────────────────────

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


def load_comp_message_state():
    if os.path.exists(COMPETITION_MESSAGE_STATE):
        with open(COMPETITION_MESSAGE_STATE, "r") as f:
            return f.read().strip()
    return None


def save_comp_message_state(message_id):
    with open(COMPETITION_MESSAGE_STATE, "w") as f:
        f.write(message_id.strip())


# ── market helpers ────────────────────────────────────────────────────────

def check_market_clock():
    eastern = zoneinfo.ZoneInfo("US/Eastern")
    now = datetime.datetime.now(eastern)
    weekday = now.weekday()
    today = now.date().isoformat()
    current_time_minutes = now.hour * 60 + now.minute
    open_minutes = 9 * 60 + 30
    close_minutes = 16 * 60
    if today in NYSE_FULL_DAY_CLOSURES_2026:
        return "ANALYTICAL_OFF_HOURS", now
    if today in NYSE_EARLY_CLOSES_2026:
        hour, minute = NYSE_EARLY_CLOSES_2026[today].split(":")
        close_minutes = int(hour) * 60 + int(minute)
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


def _read_news_lock():
    if not os.path.exists(NEWS_LOCK_FILE):
        return None
    try:
        with open(NEWS_LOCK_FILE, "r") as f:
            raw = f.read().strip()
    except OSError:
        return None
    if not raw:
        return {"owner": None, "created_at": None}
    try:
        payload = json.loads(raw)
        owner = payload.get("owner")
        created_raw = payload.get("created_at")
    except json.JSONDecodeError:
        owner = None
        created_raw = raw.splitlines()[0]
    try:
        created_at = datetime.datetime.fromisoformat(created_raw) if created_raw else None
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        created_at = None
    return {"owner": owner, "created_at": created_at}


def release_stale_news_lock(max_age_minutes=NEWS_LOCK_STALE_MINUTES):
    lock = _read_news_lock()
    if not lock:
        return False
    created_at = lock.get("created_at")
    is_stale = created_at is None
    if created_at:
        age = datetime.datetime.now(datetime.timezone.utc) - created_at
        is_stale = age >= datetime.timedelta(minutes=max_age_minutes)
    if not is_stale:
        return False
    try:
        os.remove(NEWS_LOCK_FILE)
        print("  [News] Removed stale lock before starting a new cycle.")
        return True
    except FileNotFoundError:
        return False


def acquire_news_lock():
    for attempt in range(5):
        try:
            fd = os.open(NEWS_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                json.dump({
                    "owner": NEWS_LOCK_OWNER,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }, f)
            return True
        except FileExistsError:
            release_stale_news_lock()
        print(f"  [News] Lock held — retrying ({attempt + 1}/5)...")
        time.sleep(1)
    print("  [News] Could not acquire lock.")
    return False


def release_news_lock():
    lock = _read_news_lock()
    if not lock:
        return
    owner = lock.get("owner")
    if owner and owner != NEWS_LOCK_OWNER:
        return
    try:
        os.remove(NEWS_LOCK_FILE)
    except FileNotFoundError:
        pass


# ── competition ledger ────────────────────────────────────────────────────

def load_competition_ledger():
    if os.path.exists(COMPETITION_LEDGER):
        with open(COMPETITION_LEDGER, "r") as f:
            return json.load(f)
    return {"cash_balance": STARTING_CAPITAL, "holdings": {}, "history": []}


def save_competition_ledger(ledger):
    with open(COMPETITION_LEDGER, "w") as f:
        json.dump(ledger, f, indent=2)


# ── fundamentals cache ──────────────────────────────────────────────────

def _load_fundamentals_cache():
    if os.path.exists(FUNDAMENTALS_CACHE_FILE):
        try:
            with open(FUNDAMENTALS_CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_fundamentals_cache(cache):
    with open(FUNDAMENTALS_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def record_trade(ticker, action, shares, price, trade_time=None):
    ledger = load_competition_ledger()
    if trade_time:
        try:
            parts = trade_time.replace(" ", "").split(":")
            h, m = int(parts[0]), int(parts[1])
            today = datetime.date.today()
            ts = datetime.datetime(today.year, today.month, today.day, h, m, tzinfo=datetime.timezone.utc).isoformat()
        except (ValueError, IndexError):
            ts = trade_time
    else:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if action == "buy":
        if ticker in ledger["holdings"]:
            pos = ledger["holdings"][ticker]
            total_cost = pos["shares"] * pos["avg_price"] + shares * price
            pos["shares"] += shares
            pos["avg_price"] = total_cost / pos["shares"]
        else:
            ledger["holdings"][ticker] = {"shares": shares, "avg_price": price}
        ledger["cash_balance"] -= shares * price
    elif action == "sell":
        if ticker not in ledger["holdings"]:
            return False
        pos = ledger["holdings"][ticker]
        if shares >= pos["shares"]:
            del ledger["holdings"][ticker]
        else:
            pos["shares"] -= shares
        ledger["cash_balance"] += shares * price
    portfolio_value = ledger["cash_balance"] + _holdings_value(ledger)
    ledger["history"].append({
        "timestamp": ts,
        "portfolio_value": round(portfolio_value, 2),
        "event": f"{action.upper()} {shares} {ticker} @ ${price:.2f}",
    })
    save_competition_ledger(ledger)
    generate_competition_chart(ledger)
    return True


def record_hold(ticker):
    ledger = load_competition_ledger()
    if ticker in ledger["holdings"]:
        if "confirmed_holds" not in ledger:
            ledger["confirmed_holds"] = []
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ledger["confirmed_holds"].append({"ticker": ticker, "timestamp": now})
        save_competition_ledger(ledger)
    return True


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


def send_or_update_comp_dashboard(payload, image_path=None):
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if not webhook_url:
        print(f"\n  [Comp Dash] Webhook URL not configured.")
        return
    existing_id = load_comp_message_state()
    wh_id, wh_token = parse_webhook_parts(webhook_url)
    if not wh_id or not wh_token:
        print(f"\n  [Comp Dash] Could not parse webhook URL.")
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
            print(f"\n  [Comp Dash] Dashboard message ID [{existing_id}] edited.")
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
                save_comp_message_state(new_id)
                print(f"\n  [Comp Dash] Initial dashboard message ID [{new_id}] posted and saved.")
            else:
                print(f"\n  [Comp Dash] Dashboard posted but no message ID returned.")
    except Exception as e:
        print(f"\n  [Comp Dash] Transmission failed - {e}.")
        if existing_id and getattr(getattr(e, "response", None), "status_code", None) == 404:
            print(f"  [Comp Dash] PATCH failed (404) — clearing stale ID, re-POSTing.")
            try:
                os.remove(COMPETITION_MESSAGE_STATE)
            except Exception:
                pass
            try:
                post_url = webhook_url.rstrip("/") + "?wait=true"
                if image_path and os.path.exists(image_path):
                    with open(image_path, "rb") as f:
                        resp2 = requests.post(
                            post_url,
                            data={"content": payload},
                            files={"file": (os.path.basename(image_path), f, "image/png")},
                            timeout=15
                        )
                else:
                    resp2 = requests.post(post_url, json={"content": payload}, timeout=15)
                resp2.raise_for_status()
                new_id2 = resp2.json().get("id")
                if new_id2:
                    save_comp_message_state(new_id2)
                    print(f"  [Comp Dash] Re-POSTed new dashboard message ID [{new_id2}].")
            except Exception as e2:
                print(f"  [Comp Dash] Re-POST also failed - {e2}.")


def send_batched_news(alerts, et_now):
    if not alerts:
        return
    payload = build_news_roundup(alerts, et_now)
    MAX_MSG = 2000
    TRUNC_SUFFIX = "\n... truncated"
    if len(payload) > MAX_MSG:
        cutoff = payload.rfind("\n", 0, MAX_MSG - len(TRUNC_SUFFIX))
        if cutoff < 0:
            cutoff = MAX_MSG - len(TRUNC_SUFFIX)
        payload = payload[:cutoff] + TRUNC_SUFFIX
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
            resp.raise_for_status()
            print(f"\n  [News Roundup] Edited message ID [{existing_id}] ({len(alerts)} tickers).")
        else:
            post_url = webhook_url.rstrip("/") + "?wait=true"
            resp = requests.post(post_url, json={"content": payload}, timeout=15)
            resp.raise_for_status()
            msg_id = resp.json().get("id")
            if msg_id:
                save_news_message_state(msg_id)
                print(f"\n  [News Roundup] Posted new message ID [{msg_id}] ({len(alerts)} tickers).")
            else:
                print(f"\n  [News Roundup] Posted but no message ID returned.")
    except Exception as e:
        print(f"\n  [News Roundup] Transmission failed - {e}.")
        try:
            resp_text = e.response.text[:500] if e.response is not None else ""
            if resp_text:
                print(f"  [News Roundup] Response: {resp_text}")
        except Exception:
            pass
        if existing_id and getattr(getattr(e, "response", None), "status_code", None) == 404:
            print(f"  [News Roundup] PATCH failed (404) — clearing stale message ID, re-POSTing.")
            try:
                os.remove(NEWS_MESSAGE_STATE_FILE)
            except Exception:
                pass
            try:
                post_url = webhook_url.rstrip("/") + "?wait=true"
                resp2 = requests.post(post_url, json={"content": payload}, timeout=15)
                resp2.raise_for_status()
                msg_id2 = resp2.json().get("id")
                if msg_id2:
                    save_news_message_state(msg_id2)
                    print(f"  [News Roundup] Re-POSTed new message ID [{msg_id2}] ({len(alerts)} tickers).")
            except Exception as e2:
                print(f"  [News Roundup] Re-POST also failed - {e2}.")
        elif existing_id:
            print(f"  [News Roundup] PATCH failed — keeping message ID (retry next cycle).")


# ── summarizers / builders ───────────────────────────────────────────────

def summarize_news_entry(ticker, headlines, rolling_sent, rolling_pos, rolling_neg, rolling_count, long_sent=None):
    if not headlines:
        base = f"{ticker} [{rolling_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> No headlines."
        if long_sent is not None:
            base = f"{ticker} [{rolling_sent:+.2f} / {long_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> No headlines."
        return base
    name = TICKER_NAMES.get(ticker, "").lower()
    best_h = headlines[0]
    best_net = 0.0
    best_score = -1.0
    for h in headlines:
        net, _, _ = score_headline(h)
        hl = h.lower()
        relevance = 1.0
        if ticker.lower() in hl:
            relevance = 3.0
        elif name and any(w in hl for w in name.split()):
            relevance = 2.0
        score = abs(net) + relevance
        if score > best_score:
            best_score = score
            best_h = h
            best_net = net
    if len(best_h) > 130:
        truncated = best_h[:130]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        best_h = truncated + "\u2026"
    return f"{ticker} [{best_net:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> {best_h}"


def build_news_roundup(alerts, et_now):
    pt_now = et_now.astimezone(zoneinfo.ZoneInfo("US/Pacific"))
    pt_time = pt_now.strftime('%I:%M %p').lstrip('0')
    lines = []
    lines.append("=" * 80)
    lines.append("                         GLASSBOX NEWS ROUNDUP")
    lines.append(f"  Last Fetched: {pt_now.strftime('%Y-%m-%d')} {pt_time} PT  |  Next scan in ~60 min")
    lines.append(f"  Scanner: {WATCHLIST_SCANNER_LIMIT} tickers")
    lines.append("=" * 80)
    for r in alerts:
        row = summarize_news_entry(
            r["ticker"], r.get("headlines", []),
            r["sentiment"], r["rolling_pos"], r["rolling_neg"], r["rolling_count"],
            long_sent=r.get("long_sentiment")
        )
        lines.append(f"  {row}")
    lines.append("=" * 80)
    lines.append(f"  {len(alerts)} headlines  |  24h Rolling Window  |  21d Trend Anchor")
    lines.append("=" * 80)
    return "\n".join(lines)


def build_competition_dashboard(ledger, predicted, recs, market_state, et_now, has_final_recs=False):
    pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL
    change = pv - STARTING_CAPITAL
    pct = (change / STARTING_CAPITAL) * 100
    arrow = "+" if change >= 0 else ""
    lines = []
    lines.append(f"**Glassbox Finance — COMPETITION DASHBOARD**")
    lines.append(f"Market: {market_state}  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"Portfolio: **${pv:,.2f}** ({arrow}{change:,.2f} / {arrow}{pct:.2f}%)")
    if get_scorer().using_lm:
        lines.append("**:warning: SENTIMENT ENGINE DEGRADED — using dictionary fallback**")
    lines.append(f"Cash: ${ledger['cash_balance']:,.2f}  |  Holdings: {len(ledger['holdings'])} / {MAX_PORTFOLIO_HOLDINGS}")
    lines.append("")
    if ledger["holdings"]:
        lines.append("**Real Holdings:**")
        lines.append("```")
        hdr = f"{'Ticker':<8} {'Shrs':>6} {'Now':>7} {'Val':>10} {'P&L':>9}"
        dash = "-" * len(hdr)
        lines.append(dash)
        lines.append(hdr)
        lines.append(dash)
        total_val = 0
        total_cost = 0
        for t, pos in sorted(ledger["holdings"].items()):
            cp = _get_price(t) or pos["avg_price"]
            val = pos["shares"] * cp
            cost = pos["shares"] * pos["avg_price"]
            pnl = val - cost
            pnl_s = f"{'+' if pnl >= 0 else ''}{pnl:,.2f}"
            total_val += val
            total_cost += cost
            lines.append(f"{t:<8} {pos['shares']:>6} ${cp:>6.2f} ${val:>9.2f} ${pnl_s:>8}")
        lines.append(dash)
        lines.append(f"{'TOTAL':<8} {'':>6} {'':>7} ${total_val:>9.2f} ${total_val - total_cost:>+8.2f}")
        lines.append("```")
    lines.append("")
    lines.append("**Recommendations:**")
    lines.append("```")
    lines.append(f"{'Ticker':<8} {'Rank':>6} {'Sent':>6} {'Base':>6} {'Dec':>5} {'Qty':>5}")
    dash = "-" * (8 + 6 + 6 + 6 + 5 + 5 + 5)
    lines.append(dash)
    rec_map = {rec["ticker"]: rec for rec in recs}
    for r in predicted:
        ticker = r["ticker"]
        score = r["adjusted_score"]
        fund = r["health_score"]
        sent = r["sentiment"]
        rec = rec_map.get(ticker, {})
        action = rec.get("action", "?")
        shares = rec.get("target_shares", 0)
        lines.append(f"{ticker:<8} {score:>6.1f} {sent:>+6.3f} {fund:>6.1f} {action:>5} {shares:>5}")
    lines.append(dash)
    lines.append("```")
    if has_final_recs:
        eastern = zoneinfo.ZoneInfo("US/Eastern")
        et_dt = et_now
        next_open = et_dt.replace(hour=9, minute=30, second=0, microsecond=0)
        if et_dt >= next_open or et_dt.weekday() >= 5 or et_dt.strftime("%Y-%m-%d") in NYSE_FULL_DAY_CLOSURES_2026:
            for d in range(1, 14):
                candidate = next_open + datetime.timedelta(days=d)
                if candidate.weekday() < 5 and candidate.strftime("%Y-%m-%d") not in NYSE_FULL_DAY_CLOSURES_2026:
                    next_open = candidate
                    break
        execute_by = next_open.astimezone(datetime.timezone.utc)
        ex_hhmm = execute_by.strftime("%H:%M")
        lines.append("")
        lines.append(f"**EXECUTE AT {ex_hhmm} UTC** (market opens)")
        for rec in recs:
            if rec["action"] in ("BUY", "SELL"):
                lines.append(f"`/trade ticker:{rec['ticker']} action:{rec['action'].lower()} shares:{rec['target_shares']} time:{ex_hhmm}`")
        lines.append(f"`/hold` for any HOLD positions to confirm")
    return "\n".join(lines)


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
        penalty = max(0.70, min(1.30, 1.0 + blended * SENTIMENT_IMPACT))
        return short_sent, penalty, [], short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count
    try:
        news_raw = stock.news
    except Exception:
        short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
        long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
        blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
        penalty = max(0.70, min(1.30, 1.0 + blended * SENTIMENT_IMPACT))
        return short_sent, penalty, [], short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count
    if not news_raw:
        short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
        long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
        blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
        penalty = max(0.70, min(1.30, 1.0 + blended * SENTIMENT_IMPACT))
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
        # Enrich headline with first few lines of article body for better context
        text_to_score = title
        try:
            url = (
                (content.get("canonicalUrl") or {}).get("url")
                or (content.get("clickThroughUrl") or {}).get("url")
                or ""
            )
            if url:
                from summarizer import extract_article_lead
                lead = extract_article_lead(url, max_lines=3)
                if lead:
                    text_to_score = f"{title}. {lead}"
        except Exception:
            pass
        net, pos_prob, neg_prob = score_headline(text_to_score)
        news_cache["headlines"].append({
            "text": title,
            "ticker": ticker,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pos_count": round(pos_prob, 4),
            "neg_count": round(neg_prob, 4),
            "critical_neg": 0,
            "net_score": round(net, 4),
        })
        new_count += 1
    short_sent, short_pos, short_neg, short_count = compute_rolling_sentiment(entries, ticker)
    long_sent, long_pos, long_neg, long_count = compute_rolling_sentiment(entries, ticker, window_hours=LONG_WINDOW_HOURS)
    blended = (1 - LONG_SENTIMENT_WEIGHT) * short_sent + LONG_SENTIMENT_WEIGHT * long_sent
    penalty = max(0.70, min(1.30, 1.0 + blended * SENTIMENT_IMPACT))
    if new_count > 0:
        print(f"  [{ticker}] Cached {new_count} new headline(s) | Short: {short_sent:+.3f} | 21d: {long_sent:+.3f} | Blended: {blended:+.3f}")
    return short_sent, penalty, latest_headlines, short_pos, short_neg, short_count, long_sent, long_pos, long_neg, long_count


# ── ticker processing ────────────────────────────────────────────────────

def process_ticker(ticker, index, total, news_cache):
    print(f"\n  [{index}/{total}] Processing {ticker} ...")
    fund_cache = _load_fundamentals_cache()
    cached = fund_cache.get(ticker)
    cache_fresh = False
    if cached:
        cached_at = datetime.datetime.fromisoformat(cached["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=datetime.timezone.utc)
        age = datetime.datetime.now(datetime.timezone.utc) - cached_at
        cache_fresh = age < datetime.timedelta(hours=FUNDAMENTALS_CACHE_TTL_HOURS)

    if cache_fresh:
        age_h = age.total_seconds() / 3600
        print(f"  [{index}/{total}] {ticker} fundamentals cache HIT ({age_h:.1f}h old)")
        solvency_ok = cached["solvency_ok"]
        cr = cached.get("current_ratio")
        dte = cached.get("debt_to_equity")
        valuation_multiplier = cached["valuation_multiplier"]
        health_score = cached["health_score_raw"] * valuation_multiplier
        if ticker in INSTITUTIONAL_BANKS:
            status = "PASS (Bank Neutral, cached)"
        else:
            status = "PASS (cached)" if solvency_ok else "FAIL (cached)"
        if not solvency_ok:
            directive = f"[CACHE] Would REJECT (CR={cr}, D/E={dte})."
        else:
            directive = "[CACHE] Would PASS Solvency and BUY shares."
    else:
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
            health_score_raw = 75.0
            cr = None
            dte = None
            directive = "[MOCK ACTION] Would PASS Solvency (Bank Neutral) and BUY shares."
        else:
            solvency_ok, health_score_raw, cr, dte = evaluate_solvency(bs)
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
                directive = "[MOCK ACTION] Would PASS Solvency and BUY shares."
        info = stock.info
        roe = info.get("returnOnEquity")
        if roe and roe > 0:
            roe_factor = max(0.5, min(1.5, roe / 0.20))
        else:
            roe_factor = 1.0
        if ticker in INSTITUTIONAL_BANKS:
            pb = info.get("priceToBook")
            if pb and pb > 0:
                if pb < 0.8:
                    pb_factor = 0.8
                elif 0.8 <= pb < 1.0:
                    pb_factor = 0.9
                elif 1.0 <= pb <= 1.5:
                    pb_factor = 1.0
                elif 1.5 < pb <= 2.0:
                    pb_factor = 0.9
                else:
                    pb_factor = 0.85
            else:
                pb_factor = 1.0
            valuation_multiplier = roe_factor * 0.7 + pb_factor * 0.3
        else:
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe and pe > 0:
                if pe < 5:
                    pe_factor = 0.7
                elif 5 <= pe < 10:
                    pe_factor = 0.9
                elif 10 <= pe <= 20:
                    pe_factor = 1.0
                elif 20 < pe <= 40:
                    pe_factor = 0.9
                else:
                    pe_factor = 0.8
            else:
                pe_factor = 1.0
            valuation_multiplier = roe_factor * 0.5 + pe_factor * 0.5
        health_score = health_score_raw * valuation_multiplier
        fund_cache[ticker] = {
            "solvency_ok": solvency_ok,
            "health_score_raw": health_score_raw,
            "current_ratio": cr,
            "debt_to_equity": dte,
            "valuation_multiplier": valuation_multiplier,
            "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        _save_fundamentals_cache(fund_cache)
        status = "PASS (Bank Neutral)" if ticker in INSTITUTIONAL_BANKS else ("PASS" if solvency_ok else "FAIL")
    net_sentiment, penalty, headlines, rolling_pos, rolling_neg, rolling_count, long_sent, long_pos, long_neg, long_count = sentiment_gate(yf.Ticker(ticker), ticker, news_cache, skip_fetch=True)
    if solvency_ok and net_sentiment < 0.0:
        print(f"  [{index}/{total}] [Semantic Analysis]: Computational linguistics detect high rhetorical negative sentiment across public news sources, indicating structural headline risk that down-weights our core fundamental asset valuation.")
    momentum = _get_momentum(ticker)
    momentum_multiplier = max(0.80, min(1.20, 1.0 + momentum * MOMENTUM_IMPACT))
    adjusted_score = (health_score * penalty * momentum_multiplier) if solvency_ok else health_score * momentum_multiplier
    print(f"  [{index}/{total}] {ticker} {status} (Score: {adjusted_score:.1f}/100, ValMult: {valuation_multiplier:.3f}, Mom: {momentum:+.4f})")
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
        "momentum": momentum,
        "adjusted_score": adjusted_score,
        "valuation_multiplier": valuation_multiplier,
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


# ── chart ────────────────────────────────────────────────────────────────

def _get_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.fast_info.last_price
    except Exception:
        return None


def _get_momentum(ticker):
    """Compute 5d vs 20d SMA crossover momentum. Returns -1.0 to 1.0, or 0.0 on failure."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1mo")
        if hist.empty or len(hist) < 5:
            return 0.0
        closes = hist["Close"]
        short_ma = closes.tail(5).mean()
        long_ma = closes.tail(20).mean() if len(closes) >= 20 else closes.mean()
        if long_ma <= 0:
            return 0.0
        return max(-1.0, min(1.0, (short_ma - long_ma) / long_ma))
    except Exception:
        return 0.0


def _get_price_at(ticker, time_str):
    """Fetch historical price at a given HH:MM UTC time from today's 1m bars."""
    try:
        parts = time_str.replace(" ", "").split(":")
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    today = datetime.date.today()
    target = datetime.datetime(today.year, today.month, today.day, h, m, tzinfo=datetime.timezone.utc)
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d", interval="1m")
        if hist.empty:
            return None
        hist.index = hist.index.tz_convert("UTC")
        idx = hist.index.get_indexer([target], method="nearest")
        if idx[0] >= 0:
            return float(hist["Close"].iloc[idx[0]])
        return None
    except Exception:
        return None


def _holdings_value(ledger):
    total = 0.0
    for ticker, pos in ledger["holdings"].items():
        price = _get_price(ticker)
        if price is None or price <= 0:
            price = pos["avg_price"]
        total += pos["shares"] * price
    return total


def generate_competition_chart(ledger):
    history = sorted(ledger.get("history", []), key=lambda h: h["timestamp"])
    if len(history) < 2:
        print(f"\n  {'='*70}")
        print(f"  COMPETITION PORTFOLIO CHART")
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
    ax.set_title('Competition Portfolio Performance', fontsize=16, fontweight='bold', color='white', pad=15)
    ax.set_xlabel('Time (UTC)', fontsize=12, color='white')
    ax.set_ylabel('Portfolio Value ($)', fontsize=12, color='white')
    ax.legend(loc='upper left', fontsize=11)
    ax.grid(True, alpha=0.3, color='#888888')
    ax.tick_params(colors='white')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.tight_layout()
    plt.savefig(COMPETITION_CHART, dpi=150)
    plt.close()
    print(f"  [Chart] {COMPETITION_CHART} saved ({len(history)} data points).")


# ── full evaluation ──────────────────────────────────────────────────────

def run_full_evaluation(news_cache):
    passed_results = []
    for i, ticker in enumerate(TICKERS, start=1):
        try:
            result = process_ticker(ticker, i, len(TICKERS), news_cache)
            if result is not None and result["passed"]:
                passed_results.append(result)
        except Exception as e:
            print(f"  [{i}/{len(TICKERS)}] {ticker} ERROR - {e}")
    save_news_cache(news_cache)
    predicted = sorted(passed_results, key=lambda x: x["adjusted_score"], reverse=True)[:MAX_PORTFOLIO_HOLDINGS]
    return predicted


def capped_score_weights(candidates):
    if not candidates:
        return {}
    weights = {r["ticker"]: 0.0 for r in candidates}
    remaining = list(candidates)
    remaining_weight = 1.0
    while remaining and remaining_weight > 0:
        total_score = sum(max(r["adjusted_score"], 0) for r in remaining)
        if total_score <= 0:
            equal_weight = remaining_weight / len(remaining)
            for r in remaining:
                weights[r["ticker"]] = min(MAX_POSITION_WEIGHT, equal_weight)
            break
        newly_capped = []
        for r in remaining:
            raw_weight = remaining_weight * max(r["adjusted_score"], 0) / total_score
            if raw_weight > MAX_POSITION_WEIGHT:
                weights[r["ticker"]] = MAX_POSITION_WEIGHT
                newly_capped.append(r)
        if not newly_capped:
            for r in remaining:
                weights[r["ticker"]] = remaining_weight * max(r["adjusted_score"], 0) / total_score
            break
        remaining = [r for r in remaining if r not in newly_capped]
        remaining_weight -= MAX_POSITION_WEIGHT * len(newly_capped)
    return weights


def compute_recommendations(predicted, ledger):
    eligible = [r for r in predicted if r.get("sentiment", 0) >= 0]
    eligible_tickers = {r["ticker"] for r in eligible}
    cash = ledger["cash_balance"]
    recs = []

    # Stop-loss: SELL holdings down > STOP_LOSS_PERCENT from avg_price
    stop_loss_tickers = set()
    for ticker in list(ledger["holdings"].keys()):
        pos = ledger["holdings"][ticker]
        price = _get_price(ticker)
        if price and price > 0:
            loss_pct = (price - pos["avg_price"]) / pos["avg_price"]
            if loss_pct < -STOP_LOSS_PERCENT:
                recs.append({"ticker": ticker, "action": "SELL", "target_shares": pos["shares"], "price": price})
                stop_loss_tickers.add(ticker)

    # SELL holdings with negative sentiment (not already stop-loss)
    for ticker in list(ledger["holdings"].keys()):
        if ticker in stop_loss_tickers:
            continue
        if ticker not in eligible_tickers:
            price = _get_price(ticker)
            recs.append({"ticker": ticker, "action": "SELL", "target_shares": ledger["holdings"][ticker]["shares"], "price": price})

    # Pick top 2 eligible non-stop-loss tickers: 60/40 split
    live_eligible = [r for r in eligible if r["ticker"] not in stop_loss_tickers]
    buy_tickers = []
    if live_eligible:
        splits = [(cash * 0.6, live_eligible[0]), (cash * 0.4, live_eligible[1])] if len(live_eligible) >= 2 else [(cash, live_eligible[0])]
        for alloc, candidate in splits:
            price = _get_price(candidate["ticker"])
            if price and price > 0:
                target_shares = int(alloc / price)
                if target_shares > 0:
                    recs.append({"ticker": candidate["ticker"], "action": "BUY", "target_shares": target_shares, "price": price})
                    buy_tickers.append(candidate["ticker"])

    # HOLD for remaining held tickers (not stop-loss, not negative sentiment, not in buy list)
    for r in predicted:
        ticker = r["ticker"]
        if ticker not in ledger["holdings"]:
            continue
        if ticker in stop_loss_tickers:
            continue
        if ticker not in eligible_tickers:
            continue  # Already handled as SELL above
        if ticker in buy_tickers:
            continue  # Already being bought more
        price = _get_price(ticker)
        recs.append({"ticker": ticker, "action": "HOLD", "target_shares": ledger["holdings"][ticker]["shares"], "price": price})

    # Display: buy tickers + all held tickers, in rank order
    display_tickers = set(buy_tickers)
    for t in ledger["holdings"]:
        display_tickers.add(t)
    display_list = [r for r in predicted if r["ticker"] in display_tickers]
    return recs, display_list


# ── viz update ───────────────────────────────────────────────────────────

def visualization_update(record_chart=True):
    ledger = load_competition_ledger()
    portfolio_value = ledger["cash_balance"] + _holdings_value(ledger)
    if record_chart:
        ledger["history"].append({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "portfolio_value": round(portfolio_value, 2),
        })
        MAX_HISTORY_POINTS = 500
        if len(ledger["history"]) > MAX_HISTORY_POINTS:
            ledger["history"] = ledger["history"][-MAX_HISTORY_POINTS:]
        save_competition_ledger(ledger)
        generate_competition_chart(ledger)
    else:
        if ledger["history"]:
            ledger["history"][-1]["portfolio_value"] = round(portfolio_value, 2)
        save_competition_ledger(ledger)
    return ledger


# ── reset ────────────────────────────────────────────────────────────────

def handle_reset():
    state_files = [
        GATE_FILE, NEWS_CACHE_FILE,
        MESSAGE_STATE_FILE, NEWS_MESSAGE_STATE_FILE,
        NEWS_CYCLE_FILE, NEWS_LOCK_FILE,
        COMPETITION_LEDGER, COMPETITION_MESSAGE_STATE, COMPETITION_PREDICTION_FILE,
        FUNDAMENTALS_CACHE_FILE,
    ]
    statuses = {}
    for path in state_files:
        name = os.path.basename(path)
        if os.path.exists(path):
            if name in (os.path.basename(MESSAGE_STATE_FILE), os.path.basename(NEWS_MESSAGE_STATE_FILE), os.path.basename(COMPETITION_MESSAGE_STATE)):
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
    if os.path.exists(COMPETITION_CHART):
        os.remove(COMPETITION_CHART)
        statuses[os.path.basename(COMPETITION_CHART)] = "deleted"
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

def run_news_stream(news_cache, et_now, send_roundup=True):
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
                print(f"  [News] {ticker} ({i}/{total}) — {len(headlines)} new | Short: {sent:+.3f} | 21d: {ls:+.3f}")
        except Exception as e:
            print(f"  [News] {ticker} ({i}/{total}) ERROR — {e}")
        if i < total:
            time.sleep(random.uniform(NEWS_RATE_MIN, NEWS_RATE_MAX))
    save_news_cache(news_cache)
    if send_roundup:
        send_batched_news(news_alerts, et_now)
    else:
        print("  [News] Roundup transmission skipped for worker-only mode.")
    print(f"  [News] Stream complete — {len(news_alerts)} tickers. Next cycle +60min.")


def run_news_worker(once=False, send_roundup=False):
    print(f"\n{'='*80}")
    print(f"  GLASSBOX FINANCE — News Worker")
    print(f"  Mode: {'one-shot' if once else 'continuous'}  |  Watchlist: {WATCHLIST_SCANNER_LIMIT} tickers")
    print(f"{'='*80}")
    news_cache = load_news_cache()
    repair_news_cache(news_cache)
    release_stale_news_lock()
    while True:
        _, et_now = check_market_clock()
        if acquire_news_lock():
            try:
                pruned, window_hours = prune_news_cache(news_cache)
                if pruned > 0:
                    print(f"  [Cache] Pruned {pruned} headline(s) older than {window_hours}h window.")
                run_news_stream(news_cache, et_now, send_roundup=send_roundup)
                mark_news_cycle()
            finally:
                release_news_lock()
        if once:
            break
        print(f"  [Worker] Sleeping {LOOP_INTERVAL_MINUTES}min before next fetch cycle.")
        time.sleep(LOOP_INTERVAL_MINUTES * 60)


# ── Engine Runner ────────────────────────────────────────────────────────

class EngineRunner:
    def __init__(self, run_mode="COMPETITION"):
        self.run_mode = run_mode
        self._paused = threading.Event()
        self._paused.set()
        self._stopped = threading.Event()
        self._trigger = threading.Event()
        self._thread = None
        # Clear any stale news lock from previous run
        for f in os.listdir(DATA_DIR):
            if f.startswith(".news_lock"):
                os.remove(os.path.join(DATA_DIR, f))
                print(f"  [Engine] Cleaned stale lock: {f}")
        self.status = {
            "mode": run_mode,
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
        with open(RUN_MODE_FILE, "w") as f:
            f.write(mode)

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
        print(f"  GLASSBOX FINANCE — Competition Engine")
        print(f"  Mode: {self.run_mode}  |  Watchlist: {WATCHLIST_SCANNER_LIMIT} tickers  |  Max Holdings: {MAX_PORTFOLIO_HOLDINGS}")
        print(f"{'='*80}")

        news_cache = load_news_cache()
        release_stale_news_lock()
        repair_news_cache(news_cache)

        last_viz_time = 0.0
        last_chart_time = 0.0
        news_just_fetched_this_cycle = False

        while not self._stopped.is_set():
            self._paused.wait()

            cycle_start = datetime.datetime.now(datetime.timezone.utc)
            now_ts = cycle_start.timestamp()

            pruned, window_hours = prune_news_cache(news_cache)
            if pruned > 0:
                print(f"  [Cache] Pruned {pruned} headline(s) older than {window_hours}h window.")

            market_state, et_now = check_market_clock()
            self._update_status(market_state=market_state)

            # ── Market-open scheduler ──
            if market_state == "ANALYTICAL_OFF_HOURS":
                eastern = zoneinfo.ZoneInfo("US/Eastern")
                et_dt = datetime.datetime.now(eastern)
                today_str = et_dt.date().isoformat()
                if today_str not in NYSE_FULL_DAY_CLOSURES_2026 and et_dt.weekday() < 5:
                    open_dt = datetime.datetime(et_dt.year, et_dt.month, et_dt.day, 9, 30, tzinfo=eastern)
                    if et_dt < open_dt and (open_dt - et_dt).total_seconds() <= 3600:
                        target_dt = open_dt + datetime.timedelta(minutes=5)
                        sleep_sec = (target_dt - et_dt).total_seconds()
                        print(f"  [Scheduler] Market opens at 9:30 ET — waiting {sleep_sec:.0f}s until 9:35 ET eval.")
                        self._sleep_with_trigger(sleep_sec)
                        continue

            # ── Clock 1: 60-min news cycle + full eval ──
            if check_news_cycle():
                if acquire_news_lock():
                    try:
                        run_news_stream(news_cache, et_now)
                        mark_news_cycle()
                        self._update_status(news_last_run=datetime.datetime.now(datetime.timezone.utc).isoformat())
                        news_just_fetched_this_cycle = True
                    finally:
                        release_news_lock()

            # Re-run full evaluation after news cycle so predicted allocation reflects latest sentiment
            if news_just_fetched_this_cycle:
                print(f"\n  [Eval] Running full ticker evaluation (sentiment updated)...")
                predicted = run_full_evaluation(news_cache)
                if predicted:
                    with open(COMPETITION_PREDICTION_FILE, "w") as f:
                        json.dump(predicted, f, indent=2)
                news_just_fetched_this_cycle = False

                # Compare predicted vs real ledger
                ledger = load_competition_ledger()
                recs, display = compute_recommendations(predicted, ledger)
                daily_allowed = check_daily_gate()
                has_final_recs = daily_allowed

                payload = build_competition_dashboard(ledger, display, recs, market_state, et_now, has_final_recs=has_final_recs)

                if has_final_recs:
                    mark_daily_allocation()
                    self._update_status(last_run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    print(f"  [Gate] Daily allocation window opened — recommendations issued.")
                else:
                    print(f"  [Gate] Prediction updated — gate cooldown.")

                send_or_update_comp_dashboard(payload, image_path=COMPETITION_CHART if os.path.exists(COMPETITION_CHART) else None)

                print(f"\n  Next full cycle +{LOOP_INTERVAL_MINUTES}min.")
                last_viz_time = 0.0

            # ── Clock 3: 60-second visualization ──
            if now_ts - last_viz_time >= 60:
                last_viz_time = now_ts
                record_chart = (now_ts - last_chart_time >= 300)
                if record_chart:
                    last_chart_time = now_ts
                ledger = visualization_update(record_chart=record_chart)
                self._update_status(holdings_count=len(ledger["holdings"]), portfolio_value=ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL)

                # Rebuild dashboard with latest ledger data + stored prediction
                predicted = []
                if os.path.exists(COMPETITION_PREDICTION_FILE):
                    with open(COMPETITION_PREDICTION_FILE, "r") as f:
                        predicted = json.load(f)
                recs, display = compute_recommendations(predicted, ledger) if predicted else ([], [])
                has_actionable = any(r["action"] in ("BUY", "SELL") for r in recs)
                payload = build_competition_dashboard(ledger, display, recs, market_state, et_now, has_final_recs=has_actionable)
                send_or_update_comp_dashboard(payload, image_path=COMPETITION_CHART if os.path.exists(COMPETITION_CHART) else None)

            self._sleep_with_trigger(5)
            self.clear_trigger()
