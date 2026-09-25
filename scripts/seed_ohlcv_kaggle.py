#!/usr/bin/env python
"""Bulk OHLCV ingest from the Kaggle stock-market dataset (host-run).

Reads every CSV under kaggle/stocks/ and kaggle/etfs/ (columns: Date, Open,
High, Low, Close, Adj Close, Volume; coverage 1980 → 2020-04) and inserts
into ohlcv_prices with ON CONFLICT (ticker, date) DO NOTHING — existing DB
rows always win, so this is safe to re-run and never clobbers fresher data
fetched from Yahoo.

Run from the repo root on the host (DB on localhost:5432):
    backend/.venv/bin/python scripts/seed_ohlcv_kaggle.py
"""

from __future__ import annotations

import time
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

DB_DSN = "postgresql://stocklens:stocklens@localhost:5432/stocklens"
BATCH_SIZE = 5000
MIN_ROWS = 300

REPO_ROOT = Path(__file__).resolve().parent.parent
KAGGLE_DIRS = [REPO_ROOT / "kaggle" / "stocks", REPO_ROOT / "kaggle" / "etfs"]

INSERT_SQL = """
INSERT INTO ohlcv_prices (ticker, date, open, high, low, close, adjusted_close, volume)
VALUES %s
ON CONFLICT (ticker, date) DO NOTHING
"""


def ingest_file(conn, csv_path: Path) -> int:
    """Ingest one symbol CSV; returns rows inserted."""
    import pandas as pd

    df = pd.read_csv(csv_path)
    if len(df) < MIN_ROWS:
        return 0

    ticker = csv_path.stem.upper()
    if "Adj Close" in df.columns:
        adj = df["Adj Close"]
    else:
        adj = df["Close"]

    records = []

    def num(x):
        """None → SQL NULL; NaN or |x| ≥ 1e8 (NUMERIC(12,4) overflow / bad
        split-adjusted rows) → NULL."""
        x = float(x) if x is not None else None
        if x is None or x != x or abs(x) >= 1e8:
            return None
        return x

    for date, o, h, l, c, a, v in zip(
        df["Date"],
        df["Open"],
        df["High"],
        df["Low"],
        df["Close"],
        adj,
        df["Volume"],
    ):
        records.append(
            (
                ticker,
                str(date),
                num(o),
                num(h),
                num(l),
                num(c),
                num(a),
                int(v) if v == v and v is not None else None,
            )
        )

    cur = conn.cursor()
    inserted = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        execute_values(cur, INSERT_SQL, batch, page_size=BATCH_SIZE)
        inserted += cur.rowcount
    conn.commit()
    return inserted


def main() -> None:
    start = time.time()
    files = sorted(p for d in KAGGLE_DIRS for p in d.glob("*.csv"))
    print(f"Ingesting {len(files)} CSVs from {KAGGLE_DIRS[0].parent} …")

    conn = psycopg2.connect(DB_DSN)
    total_rows = 0
    done = 0
    try:
        for path in files:
            try:
                total_rows += ingest_file(conn, path)
            except Exception as exc:  # one poison CSV must not stop the bulk load
                conn.rollback()
                print(f"  SKIP {path.name}: {type(exc).__name__}: {exc}")
            done += 1
            if done % 500 == 0:
                elapsed = time.time() - start
                rate = done / elapsed
                eta = (len(files) - done) / max(rate, 1e-9)
                print(
                    f"  {done}/{len(files)} files, {total_rows:,} rows inserted "
                    f"({elapsed:.0f}s elapsed, ETA {eta:.0f}s)"
                )
    finally:
        conn.close()

    print(f"Done: {total_rows:,} rows from {done} files in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
