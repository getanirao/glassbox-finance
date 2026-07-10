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
        print(f"  WARNING: {name} returned empty — ticker may be invalid or delisted.")
        return False
    if df.isna().all().all():
        print(f"  WARNING: {name} contains all NaN values — no financial data available.")
        return False
    return True


def evaluate_solvency(bs):
    print(f"\n{'='*80}")
    print(f"  SOLVENCY ASSESSMENT")
    print(f"{'='*80}")

    try:
        current_assets = bs.loc[bs.index.str.contains("Current Assets", case=False)].iloc[0, 0]
        current_liabilities = bs.loc[bs.index.str.contains("Current Liabilities", case=False)].iloc[0, 0]
        total_liabilities = bs.loc[bs.index.str.contains("Total Liabilities", case=False)].iloc[0, 0]
        equity = bs.loc[bs.index.str.contains("Stockholders Equity|Stockholder Equity", case=False)].iloc[0, 0]
    except (IndexError, KeyError, AttributeError) as e:
        print(f"  ERROR: Could not locate required balance-sheet line items ({e}).")
        return None, None

    current_ratio = current_assets / current_liabilities
    d_to_e = total_liabilities / equity

    print(f"  Current Assets (most recent):      ${current_assets:>14,.2f}")
    print(f"  Current Liabilities (most recent):  ${current_liabilities:>14,.2f}")
    print(f"  -------------------------------------------------")
    print(f"  Current Ratio:                      {current_ratio:>14.2f}    (threshold: >= 1.2)")
    print()
    print(f"  Total Liabilities (most recent):    ${total_liabilities:>14,.2f}")
    print(f"  Stockholders Equity (most recent):   ${equity:>14,.2f}")
    print(f"  -------------------------------------------------")
    print(f"  Debt-to-Equity Ratio:               {d_to_e:>14.2f}    (threshold: <= 1.5)")

    failures = []
    if current_ratio < 1.2:
        failures.append(
            f"  [FAIL] Current Ratio {current_ratio:.2f} < 1.2\n"
            f"         ({current_assets:,.0f} / {current_liabilities:,.0f} = {current_ratio:.2f})"
        )

    if d_to_e > 1.5:
        failures.append(
            f"  [FAIL] Debt-to-Equity {d_to_e:.2f} > 1.5\n"
            f"         ({total_liabilities:,.0f} / {equity:,.0f} = {d_to_e:.2f})"
        )

    cr_score = min(1.0, current_ratio / 1.2)
    de_score = min(1.0, 1.5 / d_to_e)
    health_score = ((cr_score + de_score) / 2) * 100

    if failures:
        print()
        for f in failures:
            print(f)
        print(f"  SOLVENCY: FAIL - Asset rejected (Health Score: {health_score:.1f}/100).")
        print(f"{'='*80}")
        return None, health_score
    else:
        print(f"  [PASS] Current Ratio {current_ratio:.2f} >= 1.2")
        print(f"  [PASS] Debt-to-Equity {d_to_e:.2f} <= 1.5")
        print(f"\n  SOLVENCY: PASS - Asset cleared (Health Score: {health_score:.1f}/100).")
        print(f"{'='*80}")
        return True, health_score


def sentiment_gate(stock, ticker):
    print(f"\n{'='*80}")
    print(f"  SENTIMENT GATE — {ticker}")
    print(f"{'='*80}")

    try:
        news = stock.news
    except Exception as e:
        print(f"  WARNING: Could not fetch news ({e}). Skipping sentiment gate.")
        return 0.0, 1.0

    if not news:
        print(f"  No recent news found. Skipping sentiment gate.")
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

    print(f"\n  Headlines scanned: {len(headlines)}")
    print(f"  Positive tokens:   {pos_count}")
    print(f"  Negative tokens:   {neg_count}")
    print(f"  Net Sentiment:     {net_score:+.3f}    (range: -1.0 to +1.0)")

    if net_score > 0.3:
        print(f"  SENTIMENT: BULLISH")
    elif net_score >= 0.0:
        print(f"  SENTIMENT: NEUTRAL")
    else:
        print(f"  SENTIMENT: BEARISH")
        print(f"\n  Sentiment penalty active: {penalty:.2f}x multiplier applied to valuation.")

    if headlines:
        print(f"\n  Recent headlines:")
        for h in headlines[:5]:
            print(f"    - {h}")

    print(f"{'='*80}")
    return net_score, penalty


check_time_gate()

try:
    ticker = input("Enter stock ticker: ").strip().upper()
    stock = yf.Ticker(ticker)

    print(f"\n{'='*80}")
    print(f"  INCOME STATEMENT — {ticker}")
    print(f"{'='*80}")
    inc = stock.income_stmt
    if not validate_statement(inc, "Income Statement"):
        sys.exit(1)
    print(inc.to_string())

    print(f"\n{'='*80}")
    print(f"  BALANCE SHEET — {ticker}")
    print(f"{'='*80}")
    bs = stock.balance_sheet
    if not validate_statement(bs, "Balance Sheet"):
        sys.exit(1)
    print(bs.to_string())

    print(f"\n{'='*80}")
    print(f"  CASH FLOW STATEMENT — {ticker}")
    print(f"{'='*80}")
    cf = stock.cashflow
    if not validate_statement(cf, "Cash Flow Statement"):
        sys.exit(1)
    print(cf.to_string())

    solvency_ok, health_score = evaluate_solvency(bs)

    if solvency_ok and health_score is not None:
        net_sentiment, penalty = sentiment_gate(stock, ticker)

        print(f"\n{'='*80}")
        print(f"  FINAL VALUATION — {ticker}")
        print(f"{'='*80}")
        print(f"  Solvency Health Score:  {health_score:.1f}/100")
        print(f"  Sentiment Score:        {net_sentiment:+.3f}")

        if net_sentiment < 0.0:
            adjusted = health_score * penalty
            print(f"  Sentiment Multiplier:   {penalty:.2f}x")
            print(f"  Adjusted Health Score:  {adjusted:.1f}/100")
        else:
            print(f"  Sentiment Multiplier:   1.00x (no penalty)")
            print(f"  Final Health Score:     {health_score:.1f}/100")

        print(f"{'='*80}")

    print(f"\n{'='*80}")
    print("  Done.")
    print(f"{'='*80}")

except Exception as e:
    print(f"  ERROR: Unexpected failure — {e}")
    sys.exit(1)
