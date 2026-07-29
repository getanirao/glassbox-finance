import os
import math
import json
import time
import datetime
import concurrent.futures
import re
import random
import threading
import shutil
import tempfile
import zoneinfo
import traceback
try:
    import fcntl
except ImportError:
    fcntl = None
import requests
import logging
_yf_logger = logging.getLogger('yfinance')
_yf_logger.disabled = True
import yfinance as yf
import pandas as pd

from config import *

from sentiment import score_headline, get_scorer

NEWS_LOCK_OWNER = f"{os.getpid()}:{datetime.datetime.now(datetime.timezone.utc).isoformat()}"
NEWS_LOCK_FD = None
COMPETITION_LEDGER_LOCK = threading.RLock()


def log_sentiment_backend():
    scorer = get_scorer()
    scorer.score("market update")
    if scorer.using_lm:
        print("  [Sentiment] FinBERT ONNX model unavailable; using Loughran-McDonald fallback.")


# ── helpers ──────────────────────────────────────────────────────────────

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_atomic(path, payload):
    """Write state files atomically so an interrupted save never truncates the live file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _valid_news_cache(data):
    return isinstance(data, dict) and isinstance(data.get("headlines"), list)


def _headline_key(ticker, text):
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()
    return f"{ticker.upper()}|{normalized}"


def _entry_timestamp(entry):
    try:
        timestamp = datetime.datetime.fromisoformat(entry["timestamp"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
        return timestamp.astimezone(datetime.timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None


def load_news_cache():
    if os.path.exists(NEWS_CACHE_FILE):
        data = _read_json(NEWS_CACHE_FILE)
        if _valid_news_cache(data):
            return data
        print("  [Cache] Main cache is unreadable; attempting backup recovery.")
        backup = _read_json(NEWS_CACHE_BACKUP)
        if _valid_news_cache(backup):
            return backup
    # A missing main cache is an intentional fresh start. Do not resurrect a backup.
    return {"headlines": [], "scoring_version": None}


def save_news_cache(cache):
    if not _valid_news_cache(cache):
        raise ValueError("News cache must contain a headlines list.")
    tickers_seen = {h.get("ticker") for h in cache["headlines"] if isinstance(h, dict)}
    if len(tickers_seen) >= len(TICKERS) * 0.5 and os.path.exists(NEWS_CACHE_FILE):
        shutil.copy2(NEWS_CACHE_FILE, NEWS_CACHE_BACKUP)
    _write_json_atomic(NEWS_CACHE_FILE, cache)


def repair_news_cache(cache):
    scorer = get_scorer()
    scorer.score("market update")
    backend = "lm" if scorer.using_lm else "onnx"
    scoring_version = f"{SENTIMENT_SCORING_VERSION}:{backend}"
    if cache.get("scoring_version") == scoring_version:
        return 0
    fixed = 0
    for h in cache["headlines"]:
        text = h.get("scored_text") or h.get("text", "")
        net, pos, neg = score_headline(text)
        old_net = h.get("net_score", 0)
        if abs(old_net - net) > 0.001:
            h["net_score"] = round(net, 4)
            h["pos_count"] = round(pos, 4)
            h["neg_count"] = round(neg, 4)
            h["critical_neg"] = 0
            fixed += 1
    cache["scoring_version"] = scoring_version
    if fixed:
        print(f"  [Cache] Repaired {fixed} headline(s) with FinBERT scores.")
    return fixed


def repair_and_persist_news_cache(cache):
    previous_version = cache.get("scoring_version")
    fixed = repair_news_cache(cache)
    if cache.get("scoring_version") != previous_version:
        save_news_cache(cache)
    return fixed


def get_cache_window_hours():
    weekday = datetime.datetime.now(datetime.timezone.utc).weekday()
    if weekday in (1, 2, 3):  # Tue–Thu
        return 24
    return 72  # Fri–Mon


def prune_news_cache(cache):
    window_hours = get_cache_window_hours()
    now = datetime.datetime.now(datetime.timezone.utc)
    short_cutoff = now - datetime.timedelta(hours=window_hours)
    long_cutoff = now - datetime.timedelta(hours=LONG_WINDOW_HOURS)
    before = len(cache["headlines"])
    surviving = []
    for h in cache["headlines"]:
        ts = _entry_timestamp(h)
        if ts is None:
            continue
        if ts >= long_cutoff:
            surviving.append(h)
    deduped = []
    seen = set()
    short_counts = {}
    historical_day_counts = {}
    for h in sorted(surviving, key=lambda item: _entry_timestamp(item), reverse=True):
        ticker = str(h.get("ticker", "")).upper()
        text = h.get("text", "")
        if not ticker or not text:
            continue
        key = _headline_key(ticker, text)
        if key in seen:
            continue
        timestamp = _entry_timestamp(h)
        if timestamp >= short_cutoff:
            if short_counts.get(ticker, 0) >= MAX_HEADLINES_PER_TICKER:
                continue
            short_counts[ticker] = short_counts.get(ticker, 0) + 1
        else:
            day_key = (ticker, timestamp.date().isoformat())
            if historical_day_counts.get(day_key, 0) >= MAX_LONG_HEADLINES_PER_TICKER_DAY:
                continue
            historical_day_counts[day_key] = historical_day_counts.get(day_key, 0) + 1
        seen.add(key)
        deduped.append(h)
    cache["headlines"] = list(reversed(deduped))
    return before - len(cache["headlines"]), window_hours


def compute_rolling_sentiment(entries, ticker, window_hours=None):
    if window_hours is None:
        window_hours = get_cache_window_hours()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=window_hours)
    now = datetime.datetime.now(datetime.timezone.utc)
    ticker_entries = []
    for h in entries:
        timestamp = _entry_timestamp(h)
        if h.get("ticker") == ticker and timestamp is not None and timestamp >= cutoff:
            ticker_entries.append(h)
    if not ticker_entries:
        return 0.0, 0, 0, 0
    name = TICKER_NAMES.get(ticker, "").lower()
    total_weight = 0.0
    weighted_net = 0.0
    positive_headlines = 0
    negative_headlines = 0
    for h in ticker_entries:
        age = now - _entry_timestamp(h)
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
        if net_score > 0.05:
            positive_headlines += 1
        elif net_score < -0.05:
            negative_headlines += 1
    avg_net = weighted_net / total_weight if total_weight > 0 else 0.0
    return avg_net, positive_headlines, negative_headlines, len(ticker_entries)


def sentiment_coverage_hours(entries, ticker, window_hours=LONG_WINDOW_HOURS):
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=window_hours)
    timestamps = [
        timestamp
        for h in entries
        if h.get("ticker") == ticker
        and (timestamp := _entry_timestamp(h)) is not None
        and timestamp >= cutoff
    ]
    if not timestamps:
        return 0.0
    return min(window_hours, max(0.0, (now - min(timestamps)).total_seconds() / 3600))


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


def save_execution_plan(recs, issued_at=None):
    issued_at = issued_at or datetime.datetime.now(datetime.timezone.utc)
    actionables = []
    for rec in recs:
        if rec.get("action") not in {"BUY", "SELL"}:
            continue
        actionables.append({
            "ticker": rec["ticker"],
            "action": rec["action"],
            "target_shares": int(rec["target_shares"]),
            "price": float(rec["price"]) if rec.get("price") else None,
            "weight": float(rec["weight"]) if rec.get("weight") is not None else None,
            "reason": rec.get("reason"),
        })
    payload = {
        "schema_version": 1,
        "issued_at": issued_at.isoformat(),
        "expires_at": (issued_at + datetime.timedelta(minutes=EXECUTION_WINDOW_MINUTES)).isoformat(),
        "recs": actionables,
    }
    _write_json_atomic(COMPETITION_EXECUTION_PLAN_FILE, payload)
    return payload


def clear_execution_plan():
    try:
        os.remove(COMPETITION_EXECUTION_PLAN_FILE)
    except FileNotFoundError:
        pass


def load_active_execution_plan(ledger=None, now=None):
    plan = _read_json(COMPETITION_EXECUTION_PLAN_FILE)
    if not isinstance(plan, dict) or not isinstance(plan.get("recs"), list):
        return None
    try:
        issued_at = datetime.datetime.fromisoformat(plan["issued_at"])
        expires_at = datetime.datetime.fromisoformat(plan["expires_at"])
    except (KeyError, TypeError, ValueError):
        clear_execution_plan()
        return None
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=datetime.timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now >= expires_at:
        clear_execution_plan()
        return None
    ledger = ledger or load_competition_ledger()
    matching_cutoff = issued_at - datetime.timedelta(minutes=2)
    fills = {}
    for trade in ledger.get("trades", []):
        if not isinstance(trade, dict) or trade.get("source") != "marketwatch":
            continue
        timestamp = _entry_timestamp(trade)
        if timestamp is None or timestamp < matching_cutoff:
            continue
        ticker = str(trade.get("ticker", "")).upper()
        action = str(trade.get("action", "")).upper()
        shares = trade.get("shares")
        if not ticker or action not in {"BUY", "SELL"} or not isinstance(shares, int):
            event = str(trade.get("event", ""))
            match = re.match(r"^(BUY|SELL)\s+(\d+)\s+([A-Z.]+)\s+@", event)
            if not match:
                continue
            action, shares, ticker = match.groups()
        key = (ticker, action)
        fills[key] = fills.get(key, 0) + int(shares)
    remaining_recs = []
    for rec in plan["recs"]:
        key = (rec.get("ticker"), rec.get("action"))
        remaining = max(0, int(rec.get("target_shares", 0)) - fills.get(key, 0))
        if remaining:
            updated = dict(rec)
            updated["target_shares"] = remaining
            remaining_recs.append(updated)
    if not remaining_recs and plan["recs"]:
        clear_execution_plan()
        return None
    result = dict(plan)
    result["issued_at"] = issued_at.isoformat()
    result["expires_at"] = expires_at.isoformat()
    result["recs"] = remaining_recs
    return result


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
    if fcntl is not None:
        # Linux advisory locks disappear automatically when a container exits.
        return False
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


def acquire_news_lock(attempts=5, retry_seconds=1):
    global NEWS_LOCK_FD
    if fcntl is not None:
        if NEWS_LOCK_FD is not None:
            return True
        for attempt in range(attempts):
            fd = os.open(NEWS_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                print(f"  [News] Lock held - retrying ({attempt + 1}/{attempts})...")
                time.sleep(retry_seconds)
                continue
            payload = json.dumps({
                "owner": NEWS_LOCK_OWNER,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }).encode("utf-8")
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, payload)
            NEWS_LOCK_FD = fd
            return True
        print("  [News] Could not acquire lock.")
        return False

    for attempt in range(attempts):
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
        print(f"  [News] Lock held — retrying ({attempt + 1}/{attempts})...")
        time.sleep(retry_seconds)
    print("  [News] Could not acquire lock.")
    return False


def release_news_lock():
    global NEWS_LOCK_FD
    if fcntl is not None:
        if NEWS_LOCK_FD is None:
            return
        try:
            fcntl.flock(NEWS_LOCK_FD, fcntl.LOCK_UN)
        finally:
            os.close(NEWS_LOCK_FD)
            NEWS_LOCK_FD = None
        return

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

def _valid_competition_ledger(ledger):
    return (
        isinstance(ledger, dict)
        and isinstance(ledger.get("holdings"), dict)
        and isinstance(ledger.get("history"), list)
    )


def _normalize_competition_ledger(ledger):
    ledger.setdefault("cash_balance", STARTING_CAPITAL)
    trades = ledger.setdefault("trades", [])
    if not isinstance(trades, list):
        raise RuntimeError("Competition trade journal is unreadable.")
    known = {entry.get("event_id") for entry in trades if isinstance(entry, dict) and entry.get("event_id")}
    observations = []
    for entry in ledger["history"]:
        if isinstance(entry, dict) and entry.get("event"):
            if not entry.get("event_id") or entry.get("event_id") not in known:
                trades.append(entry)
                if entry.get("event_id"):
                    known.add(entry["event_id"])
        else:
            observations.append(entry)
    ledger["history"] = observations
    return ledger


def load_competition_ledger():
    if os.path.exists(COMPETITION_LEDGER):
        ledger = _read_json(COMPETITION_LEDGER)
        if _valid_competition_ledger(ledger):
            return _normalize_competition_ledger(ledger)
        backup = _read_json(COMPETITION_LEDGER_BACKUP)
        if _valid_competition_ledger(backup):
            print("  [Ledger] Main ledger unreadable; restored the verified backup.")
            _write_json_atomic(COMPETITION_LEDGER, backup)
            return _normalize_competition_ledger(backup)
        raise RuntimeError("Competition ledger and backup are unreadable; refusing to reset balances.")
    return {"cash_balance": STARTING_CAPITAL, "holdings": {}, "history": [], "trades": []}


def save_competition_ledger(ledger):
    existing = _read_json(COMPETITION_LEDGER)
    if _valid_competition_ledger(existing):
        _write_json_atomic(COMPETITION_LEDGER_BACKUP, existing)
    _write_json_atomic(COMPETITION_LEDGER, ledger)


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


def _trade_timestamp(trade_time=None):
    if not trade_time:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
    raw = trade_time.strip()
    try:
        if "T" in raw or raw.count("-") >= 2:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.astimezone(datetime.timezone.utc).isoformat()
        h, m = (int(part) for part in raw.replace(" ", "").split(":"))
        today = datetime.datetime.now(datetime.timezone.utc).date()
        return datetime.datetime(today.year, today.month, today.day, h, m, tzinfo=datetime.timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise ValueError("Time must be HH:MM UTC or an ISO-8601 UTC timestamp.")


def record_trade(ticker, action, shares, price, trade_time=None, source="manual", event_id=None):
    with COMPETITION_LEDGER_LOCK:
        return _record_trade_unlocked(ticker, action, shares, price, trade_time, source, event_id)


def _record_trade_unlocked(ticker, action, shares, price, trade_time=None, source="manual", event_id=None):
    ticker = str(ticker).upper()
    action = str(action).lower()
    if ticker not in TICKERS:
        raise ValueError(f"{ticker} is not in the configured competition watchlist.")
    if action not in ("buy", "sell"):
        raise ValueError("Action must be buy or sell.")
    if not isinstance(shares, int) or shares <= 0:
        raise ValueError("Shares must be a positive whole number.")
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("Price must be a positive finite number.")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Trade source must be a non-empty string.")
    if event_id is not None and (not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 160):
        raise ValueError("Trade event ID must be a non-empty string up to 160 characters.")

    ledger = load_competition_ledger()
    ts = _trade_timestamp(trade_time)
    if action == "buy":
        cost = shares * price
        if cost > ledger["cash_balance"] + 0.01:
            raise ValueError(f"Insufficient cash: need ${cost:,.2f}, have ${ledger['cash_balance']:,.2f}.")
        if ticker in ledger["holdings"]:
            pos = ledger["holdings"][ticker]
            total_cost = pos["shares"] * pos["avg_price"] + shares * price
            pos["shares"] += shares
            pos["avg_price"] = total_cost / pos["shares"]
            pos["trim_executed"] = False
            pos["profit_taken"] = False
        else:
            if len(ledger["holdings"]) >= MAX_PORTFOLIO_HOLDINGS:
                raise ValueError(f"Portfolio already has {MAX_PORTFOLIO_HOLDINGS} holdings.")
            ledger["holdings"][ticker] = {
                "shares": shares,
                "avg_price": price,
                "trim_executed": False,
                "profit_taken": False,
            }
        ledger["cash_balance"] -= cost
    elif action == "sell":
        if ticker not in ledger["holdings"]:
            raise ValueError(f"Cannot sell {ticker}: it is not in the ledger.")
        pos = ledger["holdings"][ticker]
        if shares > pos["shares"]:
            raise ValueError(f"Cannot sell {shares} {ticker} shares; ledger holds {pos['shares']}.")
        gain_pct = (price - pos["avg_price"]) / pos["avg_price"]
        if shares == pos["shares"]:
            del ledger["holdings"][ticker]
        else:
            pos["shares"] -= shares
            if gain_pct <= -TRAILING_TRIM_PERCENT:
                pos["trim_executed"] = True
            if gain_pct >= PROFIT_TAKE_PERCENT:
                pos["profit_taken"] = True
        ledger["cash_balance"] += shares * price
    portfolio_value = ledger["cash_balance"] + _holdings_value(ledger)
    history_event = {
        "timestamp": ts,
        "portfolio_value": round(portfolio_value, 2),
        "event": f"{action.upper()} {shares} {ticker} @ ${price:.2f}",
        "ticker": ticker,
        "action": action.upper(),
        "shares": shares,
        "price": float(price),
        "source": source.strip(),
    }
    if event_id:
        history_event["event_id"] = event_id.strip()
    ledger["trades"].append(history_event)
    save_competition_ledger(ledger)
    return ledger


def record_hold(ticker):
    with COMPETITION_LEDGER_LOCK:
        return _record_hold_unlocked(ticker)


def _record_hold_unlocked(ticker):
    ledger = load_competition_ledger()
    if ticker in ledger["holdings"]:
        if "confirmed_holds" not in ledger:
            ledger["confirmed_holds"] = []
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ledger["confirmed_holds"].append({"ticker": ticker, "timestamp": now})
        save_competition_ledger(ledger)
        return True
    return False


def marketwatch_sync_status():
    """Return bridge health without making a remote call from the engine loop."""
    if not MARKETWATCH_SYNC_ENABLED:
        return {"enabled": False, "healthy": True, "status": "disabled"}
    state = _read_json(MARKETWATCH_SYNC_FILE)
    if not isinstance(state, dict):
        return {"enabled": True, "healthy": False, "status": "awaiting_baseline"}
    status = str(state.get("status", "awaiting_baseline"))
    observed_at = _entry_timestamp({"timestamp": state.get("last_observed_at")})
    if observed_at is None:
        return {"enabled": True, "healthy": False, "status": "awaiting_baseline"}
    age_seconds = (datetime.datetime.now(datetime.timezone.utc) - observed_at).total_seconds()
    if age_seconds > MARKETWATCH_SYNC_MAX_STALENESS_SECONDS:
        return {"enabled": True, "healthy": False, "status": "stale", "age_seconds": round(age_seconds)}
    return {
        "enabled": True,
        "healthy": status == "healthy",
        "status": status,
        "age_seconds": round(max(0, age_seconds)),
    }


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
                resp = requests.patch(edit_url, json={"content": payload, "attachments": []}, timeout=15)
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
    return f"{ticker} [{rolling_sent:+.2f}] ({rolling_pos} P / {rolling_neg} N) -> {best_h}"


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
    lines.append(f"  {len(alerts)} tickers  |  {get_cache_window_hours()}h Rolling Window  |  21d Trend Anchor")
    lines.append("=" * 80)
    return "\n".join(lines)


def build_competition_dashboard(
    ledger, predicted, recs, market_state, et_now,
    has_final_recs=False, execution_expires_at=None,
):
    pv = ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL
    change = pv - STARTING_CAPITAL
    pct = (change / STARTING_CAPITAL) * 100
    arrow = "+" if change >= 0 else ""
    lines = []
    lines.append(f"**Glassbox Finance — COMPETITION DASHBOARD**")
    lines.append(f"Market: {market_state}  |  {et_now.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"Portfolio: **${pv:,.2f}** ({arrow}{change:,.2f} / {arrow}{pct:.2f}%)")
    sync = marketwatch_sync_status()
    if sync["enabled"]:
        sync_label = "HEALTHY" if sync["healthy"] else f"BLOCKED ({sync['status']})"
        lines.append(f"MarketWatch bridge: **{sync_label}**")
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
    rec_map = {rec["ticker"]: rec for rec in recs}
    actionables = [r for r in recs if r["action"] in ("BUY", "SELL")]
    if actionables:
        lines.append("")
        if has_final_recs:
            execute_by = execution_expires_at or (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(minutes=EXECUTION_WINDOW_MINUTES)
            )
            if isinstance(execute_by, str):
                execute_by = datetime.datetime.fromisoformat(execute_by)
            ex_hhmm = execute_by.strftime("%H:%M")
            lines.append(f"**Trade Plan — execute by {ex_hhmm} UTC**")
        else:
            if sync["enabled"] and not sync["healthy"]:
                lines.append("**Preview only — MarketWatch sync is unhealthy.**")
            else:
                lines.append("**Recommended Actions (gate cooldown — will auto-execute next window):**")
        for rec in actionables:
            lines.append(f"`{rec['action']} {rec['target_shares']} {rec['ticker']}` {rec.get('reason', '')}")
        if has_final_recs:
            lines.append("The MarketWatch bridge imports verified fills and original timestamps automatically.")
            lines.append("HOLD positions require no action.")
    else:
        lines.append("")
        lines.append("**All positions held — no trades needed this cycle**")
    lines.append("")
    lines.append("**Scoreboard:**")
    lines.append("```")
    lines.append(f"{'Ticker':<8} {'Score':>6} {'Sent':>6} {'Health':>6} {'Wt':>6} {'Dec':>5} {'Qty':>5}  Why")
    dash = "-" * 64
    lines.append(dash)
    for r in predicted:
        ticker = r["ticker"]
        score = r["adjusted_score"]
        fund = r["health_score"]
        sent = r["sentiment"]
        rec = rec_map.get(ticker, {})
        action = rec.get("action", r.get("display_action", "DEFER"))
        shares = rec.get("target_shares", 0)
        reason = rec.get("reason", r.get("display_reason", "not_selected"))
        weight = rec.get("weight")
        weight_text = f"{weight:.1%}" if isinstance(weight, (int, float)) else "-"
        lines.append(f"{ticker:<8} {score:>6.1f} {sent:>+6.3f} {fund:>6.1f} {weight_text:>6} {action:>5} {shares:>5}  {reason[:18]}")
    lines.append(dash)
    lines.append("```")
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
        current_assets = float(bs.loc[bs.index.str.contains("Current Assets", case=False)].iloc[0, 0])
        current_liabilities = float(bs.loc[bs.index.str.contains("Current Liabilities", case=False)].iloc[0, 0])
        total_debt = float(bs.loc[bs.index.str.contains("Total Debt", case=False)].iloc[0, 0])
        equity = float(bs.loc[bs.index.str.contains("Stockholders Equity|Stockholder Equity", case=False)].iloc[0, 0])
    except (IndexError, KeyError, AttributeError, TypeError, ValueError):
        return None, None, None, None
    if not all(math.isfinite(value) for value in (current_assets, current_liabilities, total_debt, equity)):
        return None, None, None, None
    if current_assets < 0 or current_liabilities <= 0 or total_debt < 0 or equity <= 0:
        return None, None, None, None
    current_ratio = current_assets / current_liabilities
    d_to_e = total_debt / equity
    cr_score = min(1.0, current_ratio / 1.2)
    de_score = min(1.0, 1.5 / d_to_e)
    health_score = ((cr_score + de_score) / 2) * 100
    if current_ratio < 1.2 or d_to_e > 1.5:
        return False, health_score, current_ratio, d_to_e
    return True, health_score, current_ratio, d_to_e


# ── sentiment ─────────────────────────────────────────────────────────────

def _article_timestamp(content):
    """Prefer the publisher timestamp so stale feed entries do not become newly relevant."""
    for raw in (content.get("providerPublishTime"), content.get("pubDate"), content.get("displayTime")):
        if raw is None:
            continue
        try:
            if isinstance(raw, (int, float)):
                return datetime.datetime.fromtimestamp(raw, tz=datetime.timezone.utc)
            parsed = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.astimezone(datetime.timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
    return datetime.datetime.now(datetime.timezone.utc)


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
    seen_headlines = {
        _headline_key(h.get("ticker", ""), h.get("text", ""))
        for h in entries if isinstance(h, dict)
    }
    for article in news_raw:
        content = article.get("content", {})
        title = content.get("title", "") if isinstance(content, dict) else ""
        if not title:
            continue
        latest_headlines.append(title)
        headline_key = _headline_key(ticker, title)
        if headline_key in seen_headlines:
            continue
        text_to_score = title
        url = (
            (content.get("canonicalUrl") or {}).get("url")
            or (content.get("clickThroughUrl") or {}).get("url")
            or ""
        )
        if ENABLE_ARTICLE_SUMMARIZATION and url:
            try:
                from summarizer import summarize_article
                summary, _ = summarize_article(
                    url,
                    provider=SUMMARIZE_PROVIDER,
                    max_chars=SUMMARIZE_MAX_CHARS,
                )
                if summary:
                    text_to_score = f"{title}. {summary}"
            except Exception as exc:
                print(f"  [{ticker}] Article summarization skipped: {exc}")
        net, pos_prob, neg_prob = score_headline(text_to_score)
        news_cache["headlines"].append({
            "text": title,
            "scored_text": text_to_score,
            "ticker": ticker,
            "timestamp": _article_timestamp(content).isoformat(),
            "pos_count": round(pos_prob, 4),
            "neg_count": round(neg_prob, 4),
            "critical_neg": 0,
            "net_score": round(net, 4),
        })
        seen_headlines.add(headline_key)
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
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(lambda: stock.info)
                info = fut.result(timeout=30)
        except (concurrent.futures.TimeoutError, Exception):
            print(f"  [{index}/{total}] {ticker} TIMEOUT - yfinance info timed out.")
            return None
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
    long_coverage_hours = sentiment_coverage_hours(news_cache["headlines"], ticker)
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
        "long_coverage_hours": long_coverage_hours,
    }


_last_live_price = {}
_last_price_fetch = {}

def _get_price(ticker):
    now = time.monotonic()
    if ticker in _last_live_price and now - _last_price_fetch.get(ticker, 0) < PRICE_CACHE_SECONDS:
        return _last_live_price[ticker]
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.last_price
        if price and price > 0:
            _last_live_price[ticker] = price
            _last_price_fetch[ticker] = now
            return price
        return _last_live_price.get(ticker)
    except Exception:
        return _last_live_price.get(ticker)


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


def _holdings_value(ledger):
    total = 0.0
    for ticker, pos in ledger["holdings"].items():
        price = _get_price(ticker)
        if price is None or price <= 0:
            price = _last_live_price.get(ticker, pos["avg_price"])
        total += pos["shares"] * price
    return total


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
    return sorted(passed_results, key=lambda x: x["adjusted_score"], reverse=True)


def capped_score_weights(candidates):
    if not candidates:
        return {}
    weights = {r["ticker"]: 0.0 for r in candidates}
    remaining = list(candidates)
    remaining_weight = 1.0 - MIN_CASH_RESERVE_PERCENT
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


def _exposure_counts(tickers):
    sector_counts = {}
    factor_counts = {}
    for ticker in tickers:
        sector = TICKER_SECTORS.get(ticker, "Other")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        for factor, members in FACTOR_BUCKETS.items():
            if ticker in members:
                factor_counts[factor] = factor_counts.get(factor, 0) + 1
    return sector_counts, factor_counts


def _exposure_limit_reason(ticker, sector_counts, factor_counts):
    for factor, members in FACTOR_BUCKETS.items():
        if ticker in members and factor_counts.get(factor, 0) >= MAX_FACTOR_POSITIONS:
            return f"{factor}_cap"
    sector = TICKER_SECTORS.get(ticker, "Other")
    if sector_counts.get(sector, 0) >= MAX_SECTOR_POSITIONS:
        return "sector_cap"
    return None


def _add_exposure(ticker, sector_counts, factor_counts):
    sector = TICKER_SECTORS.get(ticker, "Other")
    sector_counts[sector] = sector_counts.get(sector, 0) + 1
    for factor, members in FACTOR_BUCKETS.items():
        if ticker in members:
            factor_counts[factor] = factor_counts.get(factor, 0) + 1


def compute_recommendations(predicted, ledger, all_predictions=None):
    """Build conviction-gated recommendations from the ranked allocation set."""
    if all_predictions is None:
        all_predictions = []
        if os.path.exists(COMPETITION_PREDICTION_FILE):
            loaded = _read_json(COMPETITION_PREDICTION_FILE)
            if isinstance(loaded, list):
                all_predictions = loaded
    all_prediction_map = {r["ticker"]: r for r in all_predictions if isinstance(r, dict) and "ticker" in r}
    cash = max(0.0, ledger["cash_balance"])
    recs = []
    sold_tickers = set()
    full_exit_tickers = set()
    decisions = {}

    def add_sell(ticker, shares, price, reason, full_exit=False):
        recs.append({
            "ticker": ticker,
            "action": "SELL",
            "target_shares": shares,
            "price": price,
            "reason": reason,
        })
        sold_tickers.add(ticker)
        if full_exit:
            full_exit_tickers.add(ticker)

    # Full stop-loss has priority over every other exit rule.
    for ticker, pos in ledger["holdings"].items():
        price = _get_price(ticker)
        if price and price > 0:
            loss_pct = (price - pos["avg_price"]) / pos["avg_price"]
            if loss_pct <= -STOP_LOSS_PERCENT:
                add_sell(ticker, pos["shares"], price, "stop_loss", full_exit=True)

    # Each partial exit is marked only after the matching sell is logged.
    for ticker, pos in ledger["holdings"].items():
        if ticker in sold_tickers or pos.get("trim_executed", False):
            continue
        price = _get_price(ticker)
        if price and price > 0:
            loss_pct = (price - pos["avg_price"]) / pos["avg_price"]
            if loss_pct <= -TRAILING_TRIM_PERCENT:
                add_sell(ticker, max(1, pos["shares"] // 2), price, "trailing_trim")

    for ticker, pos in ledger["holdings"].items():
        if ticker in sold_tickers or pos.get("profit_taken", False):
            continue
        price = _get_price(ticker)
        if price and price > 0:
            gain_pct = (price - pos["avg_price"]) / pos["avg_price"]
            if gain_pct >= PROFIT_TAKE_PERCENT:
                add_sell(ticker, max(1, pos["shares"] // 2), price, "profit_take")

    # A held name with negative sentiment exits.
    for ticker, pos in ledger["holdings"].items():
        if ticker in sold_tickers:
            continue
        scored = all_prediction_map.get(ticker)
        if scored is None or scored.get("sentiment", 0) < SENTIMENT_EXIT_THRESHOLD:
            price = _get_price(ticker)
            add_sell(ticker, pos["shares"], price, "sentiment_exit", full_exit=True)

    remaining_holdings = len(ledger["holdings"]) - len(full_exit_tickers)
    sector_counts, factor_counts = _exposure_counts(
        ticker for ticker in ledger["holdings"] if ticker not in full_exit_tickers
    )
    planned_holdings = remaining_holdings
    buy_candidates = []

    for candidate in predicted:
        ticker = candidate["ticker"]
        sentiment = candidate.get("sentiment", 0.0)
        long_sentiment = candidate.get("long_sentiment", 0.0)
        if ticker in ledger["holdings"] or ticker in sold_tickers:
            continue
        if not candidate.get("passed", False):
            decisions[ticker] = ("SKIP", "solvency")
            continue
        if sentiment < SENTIMENT_BUY_THRESHOLD:
            decisions[ticker] = ("SKIP", "below_conviction")
            continue
        if len(buy_candidates) >= MAX_BUYS_PER_CYCLE:
            decisions[ticker] = ("DEFER", "cycle_cap")
            continue
        if planned_holdings >= MAX_PORTFOLIO_HOLDINGS:
            decisions[ticker] = ("DEFER", "portfolio_cap")
            continue
        if (
            planned_holdings >= CORE_PORTFOLIO_HOLDINGS
            and candidate.get("long_coverage_hours", 0.0) < MIN_PERSISTENT_COVERAGE_HOURS
        ):
            decisions[ticker] = ("DEFER", "long_signal_warmup")
            continue
        if planned_holdings >= CORE_PORTFOLIO_HOLDINGS and (
            sentiment < PERSISTENT_SENTIMENT_THRESHOLD
            or long_sentiment < PERSISTENT_SENTIMENT_THRESHOLD
        ):
            decisions[ticker] = ("DEFER", "reserve_slot")
            continue
        exposure_reason = _exposure_limit_reason(ticker, sector_counts, factor_counts)
        if exposure_reason:
            decisions[ticker] = ("DEFER", exposure_reason)
            continue
        price = _get_price(ticker)
        if not price or price <= 0:
            decisions[ticker] = ("DEFER", "price_unavailable")
            continue
        if price > cash:
            decisions[ticker] = ("DEFER", "low_cash")
            continue
        selected = dict(candidate)
        selected["price"] = price
        selected["allocation_type"] = "core" if planned_holdings < CORE_PORTFOLIO_HOLDINGS else "satellite"
        buy_candidates.append(selected)
        decisions[ticker] = ("BUY", f"{selected['allocation_type']}_conviction")
        planned_holdings += 1
        _add_exposure(ticker, sector_counts, factor_counts)

    # ── Replacement pass ──
    # If high-scored candidates were DEFER/low_cash, try to fund them by selling
    # lower-scored holdings (upgrade swap).
    upgrade_funds = 0.0
    if any(d[0] == "DEFER" and d[1] == "low_cash" for d in decisions.values()):
        held_scores = {}
        for ht, hp in ledger["holdings"].items():
            if ht in sold_tickers:
                continue
            hp_pred = all_prediction_map.get(ht, {})
            held_scores[ht] = {
                "score": hp_pred.get("adjusted_score", 0),
                "shares": hp["shares"],
                "price": _get_price(ht) or 0,
            }
        for candidate in predicted:
            ticker = candidate["ticker"]
            if decisions.get(ticker) != ("DEFER", "low_cash"):
                continue
            if len(buy_candidates) >= MAX_BUYS_PER_CYCLE:
                break
            if planned_holdings >= MAX_PORTFOLIO_HOLDINGS:
                break
            cand_score = candidate.get("adjusted_score", 0)
            worst_ht = min(held_scores, key=lambda t: held_scores[t]["score"]) if held_scores else None
            if not worst_ht or held_scores[worst_ht]["score"] >= cand_score:
                continue
            ws = held_scores[worst_ht]
            proceeds = ws["shares"] * ws["price"]
            price = _get_price(ticker)
            if not price or proceeds < price:
                continue
            add_sell(worst_ht, ws["shares"], ws["price"], "upgrade_replacement", full_exit=True)
            upgrade_funds += proceeds
            del held_scores[worst_ht]
            selected = dict(candidate)
            selected["price"] = price
            selected["allocation_type"] = "upgrade"
            buy_candidates.append(selected)
            decisions[ticker] = ("BUY", "upgrade_replacement")
            planned_holdings += 1

    buy_weights = capped_score_weights(buy_candidates)
    for candidate in buy_candidates:
        weight = buy_weights.get(candidate["ticker"], 0.0)
        price = candidate["price"]
        if price and price > 0:
            avail = cash + (upgrade_funds if candidate.get("allocation_type") == "upgrade" else 0.0)
            target_shares = int((avail * weight) / price)
            if target_shares > 0:
                recs.append({
                    "ticker": candidate["ticker"],
                    "action": "BUY",
                    "target_shares": target_shares,
                    "price": price,
                    "weight": weight,
                    "reason": decisions[candidate["ticker"]][1],
                })

    for ticker, pos in ledger["holdings"].items():
        if ticker in sold_tickers:
            continue
        recs.append({"ticker": ticker, "action": "HOLD", "target_shares": pos["shares"], "price": _get_price(ticker)})

    display = []
    rec_map = {rec["ticker"]: rec for rec in recs}
    for prediction in predicted:
        row = dict(prediction)
        ticker = row["ticker"]
        rec = rec_map.get(ticker)
        if rec:
            row["display_action"] = rec["action"]
            row["display_reason"] = rec.get("reason", "holding")
        elif ticker in decisions:
            row["display_action"], row["display_reason"] = decisions[ticker]
        elif ticker in ledger["holdings"]:
            row["display_action"] = "HOLD"
            row["display_reason"] = "holding"
        else:
            row["display_action"] = "DEFER"
            row["display_reason"] = "not_selected"
        display.append(row)
    return recs, display


# ── viz update ───────────────────────────────────────────────────────────

def visualization_update(record_history=True):
    with COMPETITION_LEDGER_LOCK:
        return _visualization_update_unlocked(record_history)


def _visualization_update_unlocked(record_history=True):
    ledger = load_competition_ledger()
    portfolio_value = ledger["cash_balance"] + _holdings_value(ledger)
    if record_history:
        ledger["history"].append({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "portfolio_value": round(portfolio_value, 2),
        })
        MAX_HISTORY_POINTS = 500
        if len(ledger["history"]) > MAX_HISTORY_POINTS:
            ledger["history"] = ledger["history"][-MAX_HISTORY_POINTS:]
        save_competition_ledger(ledger)
    else:
        if ledger["history"]:
            ledger["history"][-1]["portfolio_value"] = round(portfolio_value, 2)
        save_competition_ledger(ledger)
    return ledger


# ── reset ────────────────────────────────────────────────────────────────

def _handle_reset_unlocked():
    state_files = [
        GATE_FILE, NEWS_CACHE_FILE, NEWS_CACHE_BACKUP,
        MESSAGE_STATE_FILE, NEWS_MESSAGE_STATE_FILE,
        NEWS_CYCLE_FILE,
        COMPETITION_LEDGER, COMPETITION_LEDGER_BACKUP,
        COMPETITION_MESSAGE_STATE, COMPETITION_PREDICTION_FILE,
        COMPETITION_EXECUTION_PLAN_FILE, ENGINE_HEALTH_FILE,
        FUNDAMENTALS_CACHE_FILE, OBSERVATION_FILE, RUN_MODE_FILE, MARKETWATCH_SYNC_FILE,
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
    print(f"\n{'='*80}")
    print(f"  SYSTEM RESET")
    print(f"{'='*80}")
    for name, st in statuses.items():
        print(f"  {name:<25} {st}")
    print("  PIPELINE.md              preserved (audit history is never reset)")
    print(f"  System reset complete. Ready for new epoch.")
    print(f"{'='*80}")


def handle_reset():
    """Clear state only while no engine or worker owns the shared news cache."""
    if not acquire_news_lock(attempts=300):
        raise RuntimeError("Could not acquire the news lock for reset; a worker may still be active.")
    try:
        with COMPETITION_LEDGER_LOCK:
            _handle_reset_unlocked()
    finally:
        release_news_lock()


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
    pruned, window_hours = prune_news_cache(news_cache)
    if pruned > 0:
        print(f"  [Cache] Pruned {pruned} duplicate, excess, or expired headline(s) before save ({window_hours}h window).")
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
    log_sentiment_backend()
    release_stale_news_lock()
    while True:
        _, et_now = check_market_clock()
        if acquire_news_lock():
            try:
                # Reload after acquiring the shared lock so another worker cannot be overwritten.
                news_cache = load_news_cache()
                repair_news_cache(news_cache)
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
        self._busy = threading.Event()
        self._reload_state = threading.Event()
        self._failed = threading.Event()
        self._cycle_guard = threading.Lock()
        self._thread = None
        self._failure = None
        self._last_heartbeat_monotonic = time.monotonic()
        self._last_health_write_monotonic = 0.0
        release_stale_news_lock()
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
        self._thread = threading.Thread(target=self._run_supervised, daemon=True, name="Engine")
        self._thread.start()

    def _run_supervised(self):
        try:
            self._run_loop()
        except Exception as exc:
            self._failure = repr(exc)
            self._failed.set()
            traceback.print_exc()

    def is_healthy(self):
        if self._failed.is_set() or not self._thread or not self._thread.is_alive():
            return False
        if not self._paused.is_set():
            return True
        return time.monotonic() - self._last_heartbeat_monotonic <= ENGINE_HEALTH_MAX_STALENESS_SECONDS

    def failure_detail(self):
        return self._failure

    def _heartbeat(self, force=False):
        now_monotonic = time.monotonic()
        self._last_heartbeat_monotonic = now_monotonic
        if not force and now_monotonic - self._last_health_write_monotonic < 30:
            return
        payload = {
            "healthy": True,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": self.run_mode,
        }
        _write_json_atomic(ENGINE_HEALTH_FILE, payload)
        self._last_health_write_monotonic = now_monotonic

    def stop(self):
        self._stopped.set()
        self._paused.set()

    def pause(self):
        self._paused.clear()
        with self._lock:
            self.status["paused"] = True

    def pause_and_wait(self, timeout_seconds=300):
        """Stop at a cycle boundary before destructive state work begins."""
        self.pause()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._cycle_guard:
                if not self._busy.is_set() or not self._thread or not self._thread.is_alive():
                    return True
            time.sleep(0.1)
        return False

    def request_state_reload(self):
        self._reload_state.set()

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
            self._heartbeat()

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

        log_sentiment_backend()
        self._heartbeat(force=True)
        news_cache = load_news_cache()
        release_stale_news_lock()
        repair_and_persist_news_cache(news_cache)

        last_viz_time = 0.0
        last_history_time = 0.0
        news_just_fetched_this_cycle = False
        _baseline_was_complete = False

        while not self._stopped.is_set():
            self._heartbeat()
            self._paused.wait()
            if self._stopped.is_set():
                break
            with self._cycle_guard:
                if not self._paused.is_set():
                    continue
                self._busy.set()
            if self._reload_state.is_set():
                news_cache = load_news_cache()
                repair_and_persist_news_cache(news_cache)
                self._reload_state.clear()

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
                        # The lock protects both fetch and save; reload the latest shared cache first.
                        news_cache = load_news_cache()
                        repair_and_persist_news_cache(news_cache)
                        pruned, window_hours = prune_news_cache(news_cache)
                        if pruned > 0:
                            print(f"  [Cache] Pruned {pruned} headline(s) older than {window_hours}h window.")
                        run_news_stream(news_cache, et_now)
                        mark_news_cycle()
                        self._update_status(news_last_run=datetime.datetime.now(datetime.timezone.utc).isoformat())
                        news_just_fetched_this_cycle = True
                    finally:
                        release_news_lock()

            # Re-run full evaluation after news cycle so predicted allocation reflects latest sentiment
            if news_just_fetched_this_cycle:
                print(f"\n  [Eval] Running full ticker evaluation (sentiment updated)...")
                ranked_predictions = run_full_evaluation(news_cache)
                predicted = ranked_predictions[:MAX_PORTFOLIO_HOLDINGS]
                if ranked_predictions:
                    _write_json_atomic(COMPETITION_PREDICTION_FILE, ranked_predictions)
                news_just_fetched_this_cycle = False

                # Compare predicted vs real ledger
                ledger = load_competition_ledger()
                recs, display = compute_recommendations(predicted, ledger, ranked_predictions)
                daily_allowed = check_daily_gate()
                sync_healthy = marketwatch_sync_status()["healthy"]
                should_issue = daily_allowed and market_state == "MARKET_OPEN" and sync_healthy
                active_plan = None
                dashboard_recs = recs
                execution_expires_at = None
                if should_issue:
                    if any(rec.get("action") in {"BUY", "SELL"} for rec in recs):
                        active_plan = save_execution_plan(recs)
                        dashboard_recs = active_plan["recs"]
                        execution_expires_at = active_plan["expires_at"]
                    else:
                        clear_execution_plan()
                    mark_daily_allocation()
                    self._update_status(last_run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    print(f"  [Gate] Daily allocation window opened — recommendations issued.")
                else:
                    print(f"  [Gate] Prediction updated — gate cooldown.")

                payload = build_competition_dashboard(
                    ledger, display, dashboard_recs, market_state, et_now,
                    has_final_recs=should_issue,
                    execution_expires_at=execution_expires_at,
                )

                send_or_update_comp_dashboard(payload)

                print(f"\n  Next full cycle +{LOOP_INTERVAL_MINUTES}min.")
                last_viz_time = now_ts

            # ── Clock 2: re-evaluate when bridge baseline completes ──
            sync_status = marketwatch_sync_status()
            baseline_healthy = sync_status.get("healthy", False) and sync_status.get("status") == "healthy"
            if baseline_healthy and not _baseline_was_complete:
                _baseline_was_complete = True
                print(f"\n  [Eval] Bridge baseline completed — running full evaluation...")
                news_cache = load_news_cache()
                ranked_predictions = run_full_evaluation(news_cache)
                predicted = ranked_predictions[:MAX_PORTFOLIO_HOLDINGS]
                if ranked_predictions:
                    _write_json_atomic(COMPETITION_PREDICTION_FILE, ranked_predictions)
                ledger = load_competition_ledger()
                recs, display = compute_recommendations(predicted, ledger, ranked_predictions)
                daily_allowed = check_daily_gate()
                should_issue = daily_allowed and market_state == "MARKET_OPEN" and baseline_healthy
                active_plan = None
                dashboard_recs = recs
                execution_expires_at = None
                if should_issue:
                    if any(rec.get("action") in {"BUY", "SELL"} for rec in recs):
                        active_plan = save_execution_plan(recs)
                        dashboard_recs = active_plan["recs"]
                        execution_expires_at = active_plan["expires_at"]
                    else:
                        clear_execution_plan()
                    mark_daily_allocation()
                    self._update_status(last_run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    print(f"  [Gate] Daily allocation window opened — recommendations issued.")
                else:
                    print(f"  [Gate] Prediction updated — gate cooldown.")
                payload = build_competition_dashboard(
                    ledger, display, dashboard_recs, market_state, et_now,
                    has_final_recs=should_issue,
                    execution_expires_at=execution_expires_at,
                )
                send_or_update_comp_dashboard(payload)
                last_viz_time = now_ts
            elif not baseline_healthy:
                _baseline_was_complete = False

            # ── Clock 3: 60-second visualization ──
            if now_ts - last_viz_time >= 60:
                last_viz_time = now_ts
                record_history = (now_ts - last_history_time >= 300)
                if record_history:
                    last_history_time = now_ts
                ledger = visualization_update(record_history=record_history)
                self._update_status(holdings_count=len(ledger["holdings"]), portfolio_value=ledger["history"][-1]["portfolio_value"] if ledger["history"] else STARTING_CAPITAL)

                # Rebuild dashboard with latest ledger data + stored prediction
                ranked_predictions = []
                if os.path.exists(COMPETITION_PREDICTION_FILE):
                    loaded = _read_json(COMPETITION_PREDICTION_FILE)
                    if isinstance(loaded, list):
                        ranked_predictions = loaded
                predicted = ranked_predictions[:MAX_PORTFOLIO_HOLDINGS]
                recs, display = compute_recommendations(predicted, ledger, ranked_predictions) if predicted else ([], [])
                active_plan = load_active_execution_plan(ledger)
                sync_healthy = marketwatch_sync_status()["healthy"]
                has_final_recs = bool(active_plan) and market_state == "MARKET_OPEN" and sync_healthy
                dashboard_recs = active_plan["recs"] if active_plan else recs
                payload = build_competition_dashboard(
                    ledger, display, dashboard_recs, market_state, et_now,
                    has_final_recs=has_final_recs,
                    execution_expires_at=active_plan.get("expires_at") if active_plan else None,
                )
                send_or_update_comp_dashboard(payload)

            self._sleep_with_trigger(5)
            self.clear_trigger()
            with self._cycle_guard:
                self._busy.clear()
            self._heartbeat()
