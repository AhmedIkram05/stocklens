"""Repair rows written before minor-unit quote currencies were supported.

Before the GBp fix, ``resolve_instrument`` uppercased the provider currency, so
LSE pence (``GBp``), JSE cents (``ZAc``) and TASE agorot (``ILA``) were stored
as ``GBP`` with ``fx_rate_to_gbp = 1``. The stored GBP amounts are therefore
100x too high for those tickers. This script re-resolves the affected tickers
from the provider and, only when the provider confirms a minor-unit code,
rescales the stored GBP amounts once.

Dry-run by default. Usage:

    uv run python scripts/backfill_minor_units.py
    uv run python scripts/backfill_minor_units.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.market import provider  # noqa: E402
from src.market.fx import currency_parts  # noqa: E402

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://stocklens:stocklens@localhost:5432/stocklens",
).replace("postgresql+asyncpg://", "postgresql://", 1)

_CANDIDATES = """
SELECT DISTINCT ticker FROM instruments
 WHERE currency = 'GBP'
   AND (ticker LIKE '%.L' OR ticker LIKE '%.JO' OR ticker LIKE '%.TA')
UNION
SELECT DISTINCT ticker FROM holdings
 WHERE currency = 'GBP' AND fx_rate_to_gbp = 1
   AND (ticker LIKE '%.L' OR ticker LIKE '%.JO' OR ticker LIKE '%.TA')
UNION
SELECT DISTINCT ticker FROM transactions
 WHERE currency = 'GBP' AND fx_rate_to_gbp = 1
   AND (ticker LIKE '%.L' OR ticker LIKE '%.JO' OR ticker LIKE '%.TA')
"""


async def _rate_for(code: str) -> Decimal:
    """GBP per one minor unit (e.g. GBp -> 0.01, ZAc -> ZAR * 0.01)."""
    _code, major, factor = currency_parts(code)
    if major == "GBP":
        return factor
    return await provider.fetch_fx(major) * factor


async def _backfill(apply: bool) -> None:
    conn = await asyncpg.connect(DSN)
    try:
        tickers = [r["ticker"] for r in await conn.fetch(_CANDIDATES)]
        print(f"{len(tickers)} candidate ticker(s)")

        repairs: list[tuple[str, str, Decimal]] = []
        for ticker in tickers:
            try:
                quote = await provider.fetch_quote(ticker)
            except Exception as exc:
                print(f"skip {ticker}: provider failed ({exc})")
                continue
            raw = quote.get("currency")
            if not raw:
                print(f"skip {ticker}: provider returned no currency")
                continue
            code, _major, factor = currency_parts(raw)
            if code == "GBP" or factor == 1:
                continue
            try:
                rate = await _rate_for(code)
            except Exception as exc:
                print(f"skip {ticker}: FX lookup failed ({exc})")
                continue
            repairs.append((ticker, code, rate))
            print(f"{ticker}: {code} -> GBP rate {rate}")

        if not apply:
            print("dry run — pass --apply to write")
            return

        async with conn.transaction():
            for ticker, code, rate in repairs:
                holdings = await conn.execute(
                    "UPDATE holdings SET currency = $2, fx_rate_to_gbp = $3, "
                    "average_cost_basis_gbp = average_cost_basis_gbp * $3 "
                    "WHERE ticker = $1 AND currency = 'GBP' AND fx_rate_to_gbp = 1",
                    ticker,
                    code,
                    rate,
                )
                transactions = await conn.execute(
                    "UPDATE transactions SET currency = $2, fx_rate_to_gbp = $3, "
                    "total_amount_gbp = total_amount_gbp * $3 "
                    "WHERE ticker = $1 AND currency = 'GBP' AND fx_rate_to_gbp = 1",
                    ticker,
                    code,
                    rate,
                )
                await conn.execute(
                    "UPDATE instruments SET currency = $2 WHERE ticker = $1 AND currency = 'GBP'",
                    ticker,
                    code,
                )
                print(f"repaired {ticker}: {holdings}; {transactions}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the repairs")
    args = parser.parse_args()
    asyncio.run(_backfill(args.apply))


if __name__ == "__main__":
    main()
