"""
OHLCV ingest: refresh the training universe from Yahoo's v8 chart API.

This is the data-lifecycle entry point for the weekly retraining DAG: it
appends fresh daily bars for every training ticker (plus SPY) so training
and inference always see a current price tail. Idempotent — existing
(ticker, date) rows win via ON CONFLICT DO NOTHING.

Can also be run ad hoc from the host (no Docker — Yahoo rate-limits
container egress IPs): `make seed`.

Ticker source resolution (first hit wins):
  1. --tickers argument (comma-separated)
  2. TRAINING_TICKERS env var (read by ML_CONFIG at import; "ALL" = full S&P list)
  3. ML_CONFIG.TRAINING_TICKERS (dev subset) + SPY

Usage:
  python backend/scripts/seed_ohlcv.py [--dsn "..."] [--tickers A,B,C] [--years 12]
Requires: psycopg2 (in backend/.venv and the Airflow image)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

BATCH_SIZE = 5000
DELAY = 2.0  # polite delay between tickers
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

DEFAULT_DSN = "host=localhost port=5432 dbname=stocklens user=stocklens password=stocklens"
DEFAULT_YEARS = 12  # ML_OHLCV_YEARS=10 training window + 2y buffer


def resolve_dsn(explicit: str | None) -> str:
    """DSN precedence: --dsn arg > DATABASE_DSN env > local dev default."""
    if explicit:
        return explicit
    env = os.environ.get("DATABASE_DSN", "").strip()
    if env:
        return env
    return DEFAULT_DSN


def resolve_tickers(explicit: str | None) -> list[str]:
    if explicit:
        raw = explicit
    else:
        raw = os.environ.get("TRAINING_TICKERS", "").strip()
    if raw:
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    else:
        # Lazy import: ML_CONFIG reads TRAINING_TICKERS at import time, so the
        # env var must already be set by the caller (DAG sets it per-process).
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from ml.config import ML_CONFIG  # noqa: E402

        tickers = list(ML_CONFIG.TRAINING_TICKERS)
    # Benchmark always included and never duplicated.
    benchmark = "SPY"
    return list(dict.fromkeys(tickers + [benchmark]))


def fetch(ticker: str, years: int) -> list[dict]:
    """Fetch ~N years of daily OHLCV from Yahoo v8 chart API."""
    period1 = int(datetime.now(timezone.utc).timestamp()) - years * 365 * 86400
    for host in ["query2.finance.yahoo.com", "query1.finance.yahoo.com"]:
        url = (
            f"https://{host}/v8/finance/chart/{ticker}"
            f"?period1={period1}&period2=9999999999&interval=1d"
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


def insert_rows(conn, rows: list[dict]) -> None:
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
    cur = conn.cursor()
    try:
        for b in range(0, len(values), BATCH_SIZE):
            cur.executemany(sql, values[b : b + BATCH_SIZE])
        conn.commit()
    finally:
        cur.close()


def main(dsn: str | None = None, tickers: str | None = None, years: int | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=None, help="psycopg2 key=value DSN (else DATABASE_DSN env)")
    parser.add_argument("--tickers", default=None, help="comma-separated tickers (else TRAINING_TICKERS env / ML_CONFIG)")
    parser.add_argument("--years", type=int, default=None, help="years of history to fetch (default 12)")
    args = parser.parse_args()

    dsn = resolve_dsn(dsn if dsn is not None else args.dsn)
    fetch_years: int = years if years is not None else (args.years or DEFAULT_YEARS)
    universe = resolve_tickers(tickers if tickers is not None else args.tickers)

    import psycopg2

    conn = psycopg2.connect(dsn)
    total = 0
    failed = 0

    try:
        for i, ticker in enumerate(universe):
            time.sleep(DELAY)
            try:
                rows = fetch(ticker, fetch_years)
            except Exception as e:
                print(f"  FAIL {ticker}: {e}")
                failed += 1
                continue
            if not rows:
                print(f"  EMPTY {ticker}")
                failed += 1
                continue

            insert_rows(conn, rows)
            total += len(rows)
            pct = (i + 1) / len(universe) * 100
            print(f"  [{i+1}/{len(universe)}] {ticker}: {len(rows)} rows ({total} total, {pct:.0f}%)")
    finally:
        conn.close()

    print(f"\nDone! {total} rows total, {failed}/{len(universe)} failed")
    if failed == len(universe):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
