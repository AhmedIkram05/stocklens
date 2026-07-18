"""
Seed eval test data into PostgreSQL for CI agent evaluation.

Creates a user, portfolio, holdings, transactions, cash flows, spending
categories, and sample OHLCV data — everything the agent needs to answer
the golden dataset questions.

Usage: uv run python scripts/seed_eval.py
Requires: DATABASE_URL (or defaults to local dev PG).
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import asyncpg

# Fixed UUIDs so run_experiment.py always finds them.
EVAL_USER_ID = "00000000-0000-0000-0000-000000000001"
EVAL_PORTFOLIO_ID = "00000000-0000-0000-0000-000000000010"
CATEGORY_GROCERIES = "00000000-0000-0000-0000-000000000021"
CATEGORY_DINING = "00000000-0000-0000-0000-000000000022"
CATEGORY_ENTERTAINMENT = "00000000-0000-0000-0000-000000000023"
CATEGORY_TRANSPORT = "00000000-0000-0000-0000-000000000024"
CATEGORY_UTILITIES = "00000000-0000-0000-0000-000000000025"

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://stocklens:stocklens@localhost:5432/stocklens",
).replace("postgresql+asyncpg://", "postgresql://", 1)

# Holdings to seed — ticker, shares, average cost basis (GBP)
HOLDINGS = [
    ("AAPL", 100, 185.00),
    ("MSFT", 50, 340.00),
    ("GOOGL", 75, 140.00),
    ("AMZN", 30, 150.00),
    ("NVDA", 20, 480.00),
]

# Transactions (BUY) for each holding
TRANSACTIONS = [
    ("AAPL", "BUY", 50, 180.00, date.today() - timedelta(days=180)),
    ("AAPL", "BUY", 50, 190.00, date.today() - timedelta(days=90)),
    ("MSFT", "BUY", 50, 340.00, date.today() - timedelta(days=120)),
    ("GOOGL", "BUY", 50, 135.00, date.today() - timedelta(days=150)),
    ("GOOGL", "BUY", 25, 145.00, date.today() - timedelta(days=60)),
    ("AMZN", "BUY", 30, 150.00, date.today() - timedelta(days=100)),
    ("NVDA", "BUY", 20, 480.00, date.today() - timedelta(days=45)),
]

# Sample prices (last 365 trading days) for OHLCV seeding
# Only a few weeks of sample data — enough for basic tool queries
# Prices are realistic-ish levels
_SAMPLE_PRICES: dict[str, tuple[float, float]] = {
    "AAPL": (150, 250),
    "MSFT": (300, 450),
    "GOOGL": (120, 200),
    "AMZN": (130, 200),
    "NVDA": (120, 800),
    "SPY": (400, 600),
}


def _gen_ohlcv(ticker: str) -> list[tuple]:
    """Generate sample OHLCV data for one ticker — 365 trading days."""
    lo, hi = _SAMPLE_PRICES.get(ticker, (50.0, 200.0))
    mid = (lo + hi) / 2
    rows = []
    dt = date.today() - timedelta(days=400)
    price = mid
    for _ in range(365):
        dt += timedelta(days=1)
        if dt.weekday() >= 5:
            continue  # skip weekends
        jitter = (hi - lo) * 0.02
        price += (hash(f"{ticker}{dt.isoformat()}") % 100 - 50) / 100 * jitter
        price = max(lo * 0.8, min(hi * 1.2, price))
        open_p = round(price - jitter * 0.5, 2)
        high = round(price + jitter * 0.8, 2)
        low = round(price - jitter * 0.8, 2)
        close = round(price + jitter * 0.1, 2)
        volume = int(1_000_000 + hash(str(dt)) % 5_000_000)
        rows.append((ticker, dt, open_p, high, low, close, close, volume))
    return rows


async def seed() -> None:
    conn = await asyncpg.connect(DSN)

    try:
        # ── User ──────────────────────────────────────────────────────────
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, is_active, created_at) "
            "VALUES ($1, $2, $3, $4, TRUE, $5) "
            "ON CONFLICT (id) DO NOTHING",
            EVAL_USER_ID,
            "eval@stocklens.app",
            "$2b$12$dummyhashfordevusevaluser",
            "Eval User",
            datetime.now(timezone.utc),
        )
        print("✓ User created")

        # ── Portfolio ─────────────────────────────────────────────────────
        await conn.execute(
            "INSERT INTO portfolios (id, user_id, name, description, created_at) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (id) DO NOTHING",
            EVAL_PORTFOLIO_ID,
            EVAL_USER_ID,
            "Growth Portfolio",
            "Eval test portfolio with diversified tech holdings",
            datetime.now(timezone.utc),
        )
        print("✓ Portfolio created")

        # ── Holdings ──────────────────────────────────────────────────────
        for ticker, shares, cost_basis in HOLDINGS:
            await conn.execute(
                "INSERT INTO holdings "
                "(portfolio_id, ticker, shares, average_cost_basis, currency, "
                " fx_rate_to_gbp, average_cost_basis_gbp) "
                "VALUES ($1, $2, $3, $4, 'USD', 0.80, $5) "
                "ON CONFLICT (portfolio_id, ticker) DO UPDATE SET shares = $3",
                EVAL_PORTFOLIO_ID,
                ticker,
                shares,
                cost_basis,
                round(cost_basis * 0.80, 4),
            )
        print(f"✓ {len(HOLDINGS)} holdings created")

        # ── Cash flow (initial deposit) ───────────────────────────────────
        await conn.execute(
            "INSERT INTO cash_flows (portfolio_id, amount, source, notes, created_at) "
            "VALUES ($1, $2, 'deposit', 'Initial eval deposit', $3)",
            EVAL_PORTFOLIO_ID,
            100_000.00,
            datetime.now(timezone.utc),
        )
        print("✓ Cash flow created")

        # ── Transactions ──────────────────────────────────────────────────
        for ticker, txn_type, shares, price, txn_date in TRANSACTIONS:
            total = round(shares * price, 2)
            total_gbp = round(total * 0.80, 2)
            await conn.execute(
                "INSERT INTO transactions "
                "(portfolio_id, ticker, type, shares, price_per_share, "
                " total_amount, total_amount_gbp, currency, fx_rate_to_gbp, "
                " transaction_date, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, 'USD', 0.80, $8, $9)",
                EVAL_PORTFOLIO_ID,
                ticker,
                txn_type,
                shares,
                price,
                total,
                total_gbp,
                txn_date,
                datetime.now(timezone.utc),
            )
        print(f"✓ {len(TRANSACTIONS)} transactions created")

        # ── Spending categories ──────────────────────────────────────────
        categories = [
            (
                CATEGORY_GROCERIES,
                "Groceries",
                '["tesco", "sainsbury", "waitrose", "aldi", "lidl", "asda", "morrisons"]',
            ),
            (
                CATEGORY_DINING,
                "Dining",
                '["restaurant", "cafe", "starbucks", "pret", "mcdonald", "kfc", "subway", "delivery"]',  # noqa: E501
            ),
            (
                CATEGORY_ENTERTAINMENT,
                "Entertainment",
                '["cinema", "netflix", "spotify", "disney", "concert", "theatre", "game"]',
            ),
            (
                CATEGORY_TRANSPORT,
                "Transport",
                '["uber", "lyft", "train", "bus", "tube", "fuel", "petrol", "parking"]',
            ),
            (
                CATEGORY_UTILITIES,
                "Utilities",
                '["british gas", "eon", "water", "broadband", "phone", "electricity", "council"]',
            ),
        ]
        for cid, name, keywords in categories:
            await conn.execute(
                "INSERT INTO spending_categories (id, name, description, merchant_keywords) "
                "VALUES ($1, $2, $3, $4::jsonb) "
                "ON CONFLICT (id) DO NOTHING",
                cid,
                name,
                f"Category for {name.lower()}",
                keywords,
            )
        print(f"✓ {len(categories)} spending categories created")

        # ── Spending-linked transactions (for spending queries) ──────────
        spending_txns = [
            (date.today() - timedelta(days=5), "GROC", "BUY", 1, 85.00, CATEGORY_GROCERIES),
            (date.today() - timedelta(days=10), "DINE", "BUY", 1, 45.00, CATEGORY_DINING),
            (date.today() - timedelta(days=15), "ENTC", "BUY", 1, 30.00, CATEGORY_ENTERTAINMENT),
            (date.today() - timedelta(days=20), "TRAN", "BUY", 1, 60.00, CATEGORY_TRANSPORT),
            (date.today() - timedelta(days=25), "UTIL", "BUY", 1, 120.00, CATEGORY_UTILITIES),
            (date.today() - timedelta(days=3), "GROC", "BUY", 1, 95.00, CATEGORY_GROCERIES),
            (date.today() - timedelta(days=40), "DINE", "BUY", 1, 55.00, CATEGORY_DINING),
        ]
        for txn_date, ticker, ttype, shares, price, cat_id in spending_txns:
            total = round(shares * price, 2)
            await conn.execute(
                "INSERT INTO transactions "
                "(portfolio_id, ticker, type, shares, price_per_share, "
                " total_amount, total_amount_gbp, currency, fx_rate_to_gbp, "
                " transaction_date, spending_category_id, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, 'GBP', 1.0, $8, $9, $10)",
                EVAL_PORTFOLIO_ID,
                ticker,
                ttype,
                shares,
                price,
                total,
                total,
                txn_date,
                cat_id,
                datetime.now(timezone.utc),
            )
        print(f"✓ {len(spending_txns)} spending transactions created")

        # ── Sample OHLCV data ────────────────────────────────────────────
        ohlcv_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "SPY"]
        total_ohlcv = 0
        for ticker in ohlcv_tickers:
            rows = _gen_ohlcv(ticker)
            for r in rows:
                try:
                    await conn.execute(
                        "INSERT INTO ohlcv_prices "
                        "(ticker, date, open, high, low, close, adjusted_close, volume) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                        "ON CONFLICT (ticker, date) DO NOTHING",
                        *r,
                    )
                    total_ohlcv += 1
                except Exception:
                    pass
        print(f"✓ {total_ohlcv} OHLCV rows seeded")

        # ── Instruments ──────────────────────────────────────────────────
        instrument_data = [
            ("AAPL", "USD", "NASDAQ"),
            ("MSFT", "USD", "NASDAQ"),
            ("GOOGL", "USD", "NASDAQ"),
            ("AMZN", "USD", "NASDAQ"),
            ("NVDA", "USD", "NASDAQ"),
            ("SPY", "USD", "NYSE"),
            ("GROC", "GBP", "LSE"),
            ("DINE", "GBP", "LSE"),
            ("ENTC", "GBP", "LSE"),
            ("TRAN", "GBP", "LSE"),
            ("UTIL", "GBP", "LSE"),
        ]
        for ticker, currency, exchange in instrument_data:
            await conn.execute(
                "INSERT INTO instruments (ticker, currency, exchange) "
                "VALUES ($1, $2, $3) ON CONFLICT (ticker) DO NOTHING",
                ticker,
                currency,
                exchange,
            )
        print(f"✓ {len(instrument_data)} instruments registered")

    finally:
        await conn.close()

    print("\n✅ Eval seed data complete!")
    print(f"   User ID:       {EVAL_USER_ID}")
    print(f"   Portfolio ID:  {EVAL_PORTFOLIO_ID}")
    print(f"   Holdings:      {len(HOLDINGS)}")
    print(f"   Transactions:  {len(TRANSACTIONS) + len(spending_txns)}")
    print(f"   OHLCV rows:    {total_ohlcv}")


if __name__ == "__main__":
    asyncio.run(seed())
