"""
Dev utility: seed ohlcv_prices from Yahoo Finance.

Only seeds tickers used in training (dev subset + SPY benchmark) with ~8 years
of history — enough for the 6-year training window with buffer.

Why this exists: yfinance is IP-rate-limited inside Docker (container has a
different outbound IP than the host). The backend's market endpoint uses
yfinance, so it also fails from Docker. This script fetches directly from
Yahoo's v8 chart API (which works from the host) and inserts into PG.

Usage:  python scripts/seed_ohlcv.py
Requires: psycopg2 (available on host)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
import psycopg2

# Training tickers from ML config
import sys

# Add backend/ml to path for ML_CONFIG import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "ml"))
from ml.config import ML_CONFIG  # noqa: E402

TICKERS = list(dict.fromkeys(ML_CONFIG.TRAINING_TICKERS + [ML_CONFIG.BENCHMARK_TICKER]))

DB_DSN = "host=localhost port=5432 dbname=stocklens user=stocklens password=stocklens"
BATCH_SIZE = 5000
DELAY = 2.0  # polite delay between tickers
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# 8 years back from today — enough for the 6-year training window + 2yr buffer
_PERIOD1_TS = int(datetime.now(timezone.utc).timestamp()) - 8 * 365 * 86400
PERIOD1 = str(_PERIOD1_TS)
PERIOD2 = "9999999999"


def fetch(ticker: str) -> list[dict]:
    """Fetch ~8 years of daily OHLCV from Yahoo v8 chart API."""
    for host in ["query2.finance.yahoo.com", "query1.finance.yahoo.com"]:
        url = (
            f"https://{host}/v8/finance/chart/{ticker}"
            f"?period1={PERIOD1}&period2={PERIOD2}&interval=1d"
        )
        for attempt in range(3):
            ua = USER_AGENTS[(attempt + hash(ticker)) % len(USER_AGENTS)]
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = (2 ** attempt) * 3
                    print(f"  429 on {host}, retry {attempt+1} in {wait}s")
                    time.sleep(wait)
                    continue
                raise
        else:
            continue  # host exhausted, try next
        break
    else:
        print(f"  FAIL {ticker}: all hosts exhausted")
        return []

    result = data.get("chart", {}).get("result")
    if not result:
        return []

    timestamps = result[0].get("timestamp", [])
    quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
    adjclose = result[0].get("indicators", {}).get("adjclose", [{}])[0]

    rows = []
    for i, ts in enumerate(timestamps):
        dt = datetime.utcfromtimestamp(ts).date()
        # No date filter — accept all available history (~8 years)
        rows.append({
            "ticker": ticker,
            "date": dt,
            "open": _d(quotes.get("open", [None] * len(timestamps))[i]),
            "high": _d(quotes.get("high", [None] * len(timestamps))[i]),
            "low": _d(quotes.get("low", [None] * len(timestamps))[i]),
            "close": _d(quotes.get("close", [None] * len(timestamps))[i]),
            "adjusted_close": _d(adjclose.get("adjclose", [None] * len(timestamps))[i]),
            "volume": int(v) if (v := quotes.get("volume", [None] * len(timestamps))[i]) else None,
        })
    return rows


def _d(v):
    return None if v is None else Decimal(str(v))


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    total = 0
    failed = 0

    for i, ticker in enumerate(TICKERS):
        time.sleep(DELAY)
        try:
            rows = fetch(ticker)
        except Exception as e:
            print(f"  FAIL {ticker}: {e}")
            failed += 1
            continue
        if not rows:
            print(f"  EMPTY {ticker}")
            failed += 1
            continue

        values = [
            (r["ticker"], r["date"], r["open"], r["high"], r["low"],
             r["close"], r["adjusted_close"], r["volume"])
            for r in rows
        ]
        sql = """
            INSERT INTO ohlcv_prices
                (ticker, date, open, high, low, close, adjusted_close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, date) DO NOTHING
        """
        for b in range(0, len(values), BATCH_SIZE):
            cur.executemany(sql, values[b : b + BATCH_SIZE])
        conn.commit()
        total += len(rows)
        pct = (i + 1) / len(TICKERS) * 100
        print(f"  [{i+1}/{len(TICKERS)}] {ticker}: {len(rows)} rows ({total} total, {pct:.0f}%)")

    cur.close()
    conn.close()
    print(f"\nDone! {total} rows total, {failed}/{len(TICKERS)} failed")


if __name__ == "__main__":
    main()
