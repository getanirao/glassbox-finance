"""Fail-closed receiver for the unpacked MarketWatch portfolio bridge."""

import datetime
import hmac
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import (
    MARKETWATCH_GAME_SLUG,
    MARKETWATCH_SYNC_ENABLED,
    MARKETWATCH_SYNC_FILE,
    MARKETWATCH_SYNC_HOST,
    MARKETWATCH_SYNC_PORT,
    MARKETWATCH_SYNC_TOKEN,
    STARTING_CAPITAL,
    TICKERS,
)
from engine import (
    COMPETITION_LEDGER_LOCK,
    _read_json,
    _write_json_atomic,
    load_competition_ledger,
    record_trade,
)

MAX_REQUEST_BYTES = 256 * 1024
MAX_ACTIVITY_ROWS = 500
MAX_PROCESSED_EVENTS = 2_000
SYNC_LOCK = threading.RLock()


def _default_state():
    return {
        "schema_version": 1,
        "game_slug": MARKETWATCH_GAME_SLUG,
        "status": "awaiting_baseline",
        "baseline_complete": False,
        "last_observed_at": None,
        "last_received_at": None,
        "last_error": None,
        "processed_event_ids": [],
    }


def _load_state():
    state = _read_json(MARKETWATCH_SYNC_FILE)
    if not isinstance(state, dict):
        return _default_state()
    merged = _default_state()
    merged.update(state)
    if not isinstance(merged.get("processed_event_ids"), list):
        merged["processed_event_ids"] = []
    return merged


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_timestamp(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required and must be ISO-8601.")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone.")
    return parsed.astimezone(datetime.timezone.utc)


def _finite_number(value, label, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{label} must be {'non-negative' if allow_zero else 'positive'}.")
    return float(value)


def _positive_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive whole number.")
    return value


def _normalized_activity(rows):
    if not isinstance(rows, list) or len(rows) > MAX_ACTIVITY_ROWS:
        raise ValueError("activity must contain at most 500 rows.")
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each activity row must be an object.")
        event_id = row.get("event_id")
        ticker = str(row.get("ticker", "")).upper()
        action = str(row.get("action", "")).lower()
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 160:
            raise ValueError("Each activity row needs a stable event_id up to 160 characters.")
        if event_id in seen:
            raise ValueError("activity contains duplicate event IDs.")
        if ticker not in TICKERS:
            raise ValueError(f"Activity ticker {ticker or '<missing>'} is outside the configured watchlist.")
        if action not in {"buy", "sell"}:
            raise ValueError("Activity action must be buy or sell.")
        executed_at = _parse_timestamp(row.get("executed_at"), "activity.executed_at")
        normalized.append({
            "event_id": event_id.strip(),
            "ticker": ticker,
            "action": action,
            "shares": _positive_int(row.get("shares"), "activity.shares"),
            "price": _finite_number(row.get("price"), "activity.price"),
            "executed_at": executed_at.isoformat(),
        })
        seen.add(event_id)
    return sorted(normalized, key=lambda row: (row["executed_at"], row["event_id"]))


def _normalized_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object.")
    if snapshot.get("positions_complete") is not True:
        raise ValueError("The extension must capture a complete Portfolio table before syncing.")
    positions = snapshot.get("positions")
    if not isinstance(positions, list) or len(positions) > 100:
        raise ValueError("snapshot.positions must contain at most 100 rows.")
    normalized = {}
    for row in positions:
        if not isinstance(row, dict):
            raise ValueError("Each snapshot position must be an object.")
        ticker = str(row.get("ticker", "")).upper()
        if ticker not in TICKERS:
            raise ValueError(f"Portfolio ticker {ticker or '<missing>'} is outside the configured watchlist.")
        if ticker in normalized:
            raise ValueError(f"Portfolio contains duplicate ticker {ticker}.")
        normalized[ticker] = _positive_int(row.get("shares"), "snapshot.positions.shares")
    cash = snapshot.get("cash_balance")
    if cash is not None:
        cash = _finite_number(cash, "snapshot.cash_balance", allow_zero=True)
    return {"positions": normalized, "cash_balance": cash}


def _ledger_is_fresh(ledger):
    return (
        not ledger.get("holdings")
        and not ledger.get("history")
        and abs(float(ledger.get("cash_balance", STARTING_CAPITAL)) - STARTING_CAPITAL) < 0.01
    )


def _ledger_event_ids(ledger):
    return {
        str(entry["event_id"])
        for entry in ledger.get("history", [])
        if isinstance(entry, dict) and entry.get("source") == "marketwatch" and entry.get("event_id")
    }


def _reconcile_snapshot(ledger, snapshot):
    ledger_positions = {
        ticker: int(position["shares"])
        for ticker, position in ledger.get("holdings", {}).items()
    }
    if ledger_positions != snapshot["positions"]:
        return "Portfolio shares do not match the replayed MarketWatch activity."
    if snapshot["cash_balance"] is not None and abs(ledger["cash_balance"] - snapshot["cash_balance"]) > 0.05:
        return "Portfolio cash does not match the replayed MarketWatch activity."
    return None


def process_snapshot(envelope):
    """Replay new activity rows and fail closed if the visible portfolio disagrees."""
    if not isinstance(envelope, dict):
        raise ValueError("Request body must be a JSON object.")
    if envelope.get("schema_version") != 1:
        raise ValueError("Unsupported bridge schema version.")
    if envelope.get("game_slug") != MARKETWATCH_GAME_SLUG:
        raise ValueError("Bridge payload targets a different MarketWatch game.")
    observed_at = _parse_timestamp(envelope.get("observed_at"), "observed_at")
    if observed_at > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5):
        raise ValueError("observed_at cannot be in the future.")
    snapshot = _normalized_snapshot(envelope.get("snapshot"))
    activity = _normalized_activity(envelope.get("activity", []))

    with SYNC_LOCK, COMPETITION_LEDGER_LOCK:
        state = _load_state()
        ledger = load_competition_ledger()
        if not state["baseline_complete"] and not _ledger_is_fresh(ledger):
            state.update({
                "status": "blocked_existing_ledger",
                "last_observed_at": observed_at.isoformat(),
                "last_received_at": _now_iso(),
                "last_error": "Reset the Glassbox ledger before importing the first MarketWatch baseline.",
            })
            _write_json_atomic(MARKETWATCH_SYNC_FILE, state)
            return 409, {"accepted": False, "status": state["status"], "detail": state["last_error"]}

        known_ids = set(state["processed_event_ids"]) | _ledger_event_ids(ledger)
        imported = 0
        duplicates = 0
        try:
            for event in activity:
                if event["event_id"] in known_ids:
                    duplicates += 1
                    continue
                record_trade(
                    event["ticker"], event["action"], event["shares"], event["price"],
                    trade_time=event["executed_at"], source="marketwatch", event_id=event["event_id"],
                )
                known_ids.add(event["event_id"])
                imported += 1
            ledger = load_competition_ledger()
            mismatch = _reconcile_snapshot(ledger, snapshot)
        except ValueError as exc:
            mismatch = str(exc)

        state.update({
            "baseline_complete": mismatch is None,
            "status": "healthy" if mismatch is None else "blocked_reconciliation",
            "last_observed_at": observed_at.isoformat(),
            "last_received_at": _now_iso(),
            "last_error": mismatch,
            "processed_event_ids": list(known_ids)[-MAX_PROCESSED_EVENTS:],
        })
        _write_json_atomic(MARKETWATCH_SYNC_FILE, state)
        if mismatch:
            return 409, {"accepted": False, "status": state["status"], "detail": mismatch, "imported": imported}
        return 200, {"accepted": True, "status": "healthy", "imported": imported, "duplicates": duplicates}


class _Handler(BaseHTTPRequestHandler):
    server_version = "GlassboxMarketWatchSync/1.0"

    def _send(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self):
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {MARKETWATCH_SYNC_TOKEN}"
        return bool(MARKETWATCH_SYNC_TOKEN) and hmac.compare_digest(supplied, expected)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if self.path != "/v1/marketwatch/health":
            self._send(404, {"detail": "not found"})
            return
        state = _load_state()
        self._send(200, {
            "service": "marketwatch-sync",
            "enabled": MARKETWATCH_SYNC_ENABLED,
            "configured": bool(MARKETWATCH_SYNC_TOKEN),
            "status": state["status"],
        })

    def do_POST(self):
        if self.path != "/v1/marketwatch/snapshot":
            self._send(404, {"detail": "not found"})
            return
        if not MARKETWATCH_SYNC_ENABLED or not MARKETWATCH_SYNC_TOKEN:
            self._send(503, {"detail": "MarketWatch sync is not configured."})
            return
        if not self._authorized():
            self._send(401, {"detail": "unauthorized"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send(413, {"detail": "invalid request size"})
            return
        try:
            envelope = json.loads(self.rfile.read(content_length).decode("utf-8"))
            status, payload = process_snapshot(envelope)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            status, payload = 422, {"accepted": False, "detail": str(exc)}
        self._send(status, payload)

    def log_message(self, format, *args):
        print(f"  [MarketWatch Sync] {self.address_string()} - {format % args}")


class MarketWatchSyncServer:
    def __init__(self):
        self._server = None
        self._thread = None

    def start(self):
        if not MARKETWATCH_SYNC_ENABLED:
            print("  [MarketWatch Sync] Disabled. Set MARKETWATCH_SYNC_ENABLED=true after HTTPS is configured.")
            return False
        if not MARKETWATCH_SYNC_TOKEN:
            print("  [MarketWatch Sync] Disabled: MARKETWATCH_SYNC_TOKEN is not configured.")
            return False
        self._server = ThreadingHTTPServer((MARKETWATCH_SYNC_HOST, MARKETWATCH_SYNC_PORT), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="MarketWatchSync")
        self._thread.start()
        print(f"  [MarketWatch Sync] Listening on {MARKETWATCH_SYNC_HOST}:{MARKETWATCH_SYNC_PORT}.")
        return True

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
