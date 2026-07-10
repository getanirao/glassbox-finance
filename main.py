import sys
import os
import datetime
import re
import yfinance as yf
import pandas as pd

pd.set_option("display.max_columns", 10)
pd.set_option("display.width", 120)
pd.set_option("display.max_rows", 200)

GATE_FILE = ".last_run"
GATE_HOURS = 24

TICKERS = ["AAPL", "MSFT", "GOOGL", "JPM", "GS", "JNJ", "PFE", "AMZN", "WMT", "XOM"]

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


def check_time_gate():
    now = datetime.datetime.now(datetime.timezone.utc)

    if not os.path.exists(GATE_FILE):
        with open(GATE_FILE, "w") as f:
            f.write(now.isoformat())
        return True

    with open(GATE_FILE, "r") as f:
        stored = f.read().strip()

    try:
        last_run = datetime.datetime.fromisoformat(stored)
    except ValueError:
        with open(GATE_FILE, "w") as f:
            f.write(now.isoformat())
        return True

    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=datetime.timezone.utc)

    elapsed = now - last_run

    if elapsed >= datetime.timedelta(hours=GATE_HOURS):
        with open(GATE_FILE, "w") as f:
            f.write(now.isoformat())
        return True

    remaining = datetime.timedelta(hours=GATE_HOURS) - elapsed
    total_minutes = int(remaining.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)

    print(f"\n{'='*80}")
    print(f"  TIME COOLDOWN GATE")
    print(f"{'='*80}")
    print(f"  Last run:        {last_run.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Cooldown period: {GATE_HOURS} hours")
    print(f"  Time remaining:  {hours}h {minutes}m until gate opens")
    print(f"{'='*80}")
    print(f"\n  GATE CLOSED - Evaluation loop blocked.")
    sys.exit(0)


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


def sentiment_gate(stock):
    try:
        news = stock.news
    except Exception:
        return 0.0, 1.0

    if not news:
        return 0.0, 1.0

    headlines = []
    for article in news:
        content = article.get("content", {})
        title = content.get("title", "") if isinstance(content, dict) else ""
        if title:
            headlines.append(title)

    combined = " ".join(headlines).lower()
    tokens = re.findall(r"[a-z]+", combined)

    pos_count = sum(1 for t in tokens if t in POSITIVE_LEXICON)
    neg_count = sum(1 for t in tokens if t in NEGATIVE_LEXICON)
    total_signal = pos_count + neg_count

    if total_signal == 0:
        net_score = 0.0
    else:
        net_score = (pos_count - neg_count) / total_signal

    net_score = max(-1.0, min(1.0, net_score))

    penalty = 1.0
    if net_score < 0.0:
        penalty = 1.0 + (net_score * 0.3)
        penalty = max(0.70, penalty)

    return net_score, penalty


def process_ticker(ticker, index, total):
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

    solvency_ok, health_score, cr, dte = evaluate_solvency(bs)
    if solvency_ok is None:
        print(f"  [{index}/{total}] {ticker} SKIPPED - Solvency line items not found.")
        return None

    if not solvency_ok:
        print(f"  [{index}/{total}] {ticker} FAILED solvency (CR={cr:.2f}, D/E={dte:.2f}).")
        return None

    net_sentiment, penalty = sentiment_gate(stock)
    adjusted_score = health_score * penalty

    print(f"  [{index}/{total}] {ticker} PASSED (Score: {adjusted_score:.1f}/100)")

    return {
        "ticker": ticker,
        "health_score": health_score,
        "current_ratio": cr,
        "debt_to_equity": dte,
        "sentiment": net_sentiment,
        "penalty": penalty,
        "adjusted_score": adjusted_score,
    }


def display_portfolio_table(results):
    if not results:
        print(f"\n{'='*80}")
        print(f"  PORTFOLIO RESULT")
        print(f"{'='*80}")
        print(f"  No tickers passed all gates. Portfolio is empty.")
        print(f"{'='*80}")
        return

    total_score = sum(r["adjusted_score"] for r in results)

    print(f"\n{'='*80}")
    print(f"  PORTFOLIO RANKING TABLE")
    print(f"{'='*80}")
    print(f"  {'Ticker':<8} {'Health':>8} {'CR':>8} {'D/E':>8} {'Sent':>8} {'Penalty':>8} {'Final':>8} {'Weight':>8}")
    print(f"  {'------':<8} {'------':>8} {'---':>8} {'----':>8} {'----':>8} {'-------':>8} {'-----':>8} {'------':>8}")

    for r in sorted(results, key=lambda x: x["adjusted_score"], reverse=True):
        weight = (r["adjusted_score"] / total_score * 100) if total_score > 0 else 0
        print(f"  {r['ticker']:<8} {r['health_score']:>7.1f} {r['current_ratio']:>7.2f} {r['debt_to_equity']:>7.2f} {r['sentiment']:>+7.3f} {r['penalty']:>7.2f}x {r['adjusted_score']:>7.1f} {weight:>6.1f}%")

    print(f"  {'------':<8} {'------':>8} {'---':>8} {'----':>8} {'----':>8} {'-------':>8} {'-----':>8} {'------':>8}")
    print(f"  {'TOTAL':<8} {'':>8} {'':>8} {'':>8} {'':>8} {'':>8} {total_score:>7.1f} {'100.0%':>8}")
    print(f"{'='*80}")


def main():
    check_time_gate()

    print(f"\n{'='*80}")
    print(f"  PHASE 3 — PORTFOLIO-WIDE EVALUATION")
    print(f"  Universe: {len(TICKERS)} tickers across Technology, Finance, Healthcare, Consumer, Energy")
    print(f"{'='*80}")

    results = []
    total = len(TICKERS)

    for i, ticker in enumerate(TICKERS, start=1):
        try:
            result = process_ticker(ticker, i, total)
            if result is not None:
                results.append(result)
        except Exception as e:
            print(f"  [{i}/{total}] {ticker} ERROR - {e}")

    display_portfolio_table(results)

    print(f"\n{'='*80}")
    print("  Done.")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
