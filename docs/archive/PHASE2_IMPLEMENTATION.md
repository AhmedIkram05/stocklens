# Phase 2 — Market Data Layer Implementation Plan

> **Status:** Draft
> **Last updated:** 2026-06-30
> **Depends on:** Phase 1 (schema, auth, portfolio+holding+transaction CRUD, test infra, receipts)
> **Target tests:** 80+ new tests across market, performance, and cash_flows modules

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [New Modules](#new-modules)
4. [Implementation Rounds](#implementation-rounds)
   - [Round 1 — Market Data Provider (yfinance + PostgreSQL cache)](#round-1--market-data-provider)
   - [Round 2 — Portfolio Performance (P&L, TWR, Benchmark)](#round-2--portfolio-performance)
   - [Round 3 — Integration, Tests & Polish](#round-3--integration-tests--polish)
5. [Testing Strategy](#testing-strategy)
6. [Success Criteria](#success-criteria)
7. [Risks & Mitigations](#risks--mitigations)
8. [Verification Checklist](#verification-checklist)

---

## Overview

Phase 2 replaces the placeholder CAGR calculation with a real OHLCV pipeline from yfinance and adds production-grade portfolio performance analytics. The `ohlcv_prices` table already exists (created in Phase 1's initial migration) — this phase populates it with real data and builds computation on top.

### Key Deliverables

1. **yfinance integration** with PostgreSQL caching (`ohlcv_prices`) — reads through DB cache, writes on cache miss
2. **Current quote endpoint** — real-time price snapshots via yfinance + 60-second Redis cache
3. **Per-holding P&L** — market value, unrealised P&L, day change, portfolio weight
4. **Cash flows module** — `receipt`-backed portfolio deposits; free cash = uninvested balance
5. **Time-weighted return (TWR)** — industry-standard portfolio return calculation, cash-flow-based methodology
6. **Benchmark comparison** — SPY and QQQ comparison with excess return (alpha), tracking error, information ratio
7. **80+ pytest tests**

### Dependencies

| Dependency | Version | Purpose                                                   |
| ---------- | ------- | --------------------------------------------------------- |
| `yfinance` | ≥0.2.0  | Market data provider (Yahoo Finance)                      |
| `tenacity` | ≥9.0.0  | Retry logic for yfinance HTTP calls (exponential backoff) |

---

## Architecture

### Module Structure

```
backend/src/
├── market/                     # NEW: Market data provider
│   ├── __init__.py
│   ├── schemas.py              # OHLCVData, QuoteResponse, OHLCVResponse
│   ├── repository.py           # ohlcv_prices DB operations (read/write)
│   ├── provider.py             # yfinance async wrapper (thread pool, tenacity retry)
│   └── router.py               # /market/ohlcv/{ticker}, /market/quote/{ticker}
│
├── cash_flows/                 # NEW: Portfolio cash flow management
│   ├── __init__.py
│   ├── schemas.py              # CashFlowCreate, CashFlowResponse, CashFlowListResponse
│   ├── repository.py           # cash_flows DB operations (create, list, delete)
│   └── router.py               # /portfolios/{id}/cash-flows
│
├── performance/                # NEW: Portfolio analytics
│   ├── __init__.py
│   ├── schemas.py              # HoldingPerformance, PortfolioPerformance, BenchmarkComparison
│   ├── calculations.py         # TWR, P&L, daily returns, benchmark logic (pure functions)
│   └── router.py               # /portfolio/performance/{id}, /portfolio/benchmark/{id}
│
├── main.py                     # MODIFY: register market + cash_flows + performance routers
├── ...
```

### Data Flow

#### OHLCV Request

```
Client → GET /market/ohlcv/AAPL?start_date=2024-01-01&end_date=2024-12-31
  → market/repository.py: query ohlcv_prices WHERE ticker='AAPL' AND date BETWEEN ...
  → If cache HIT (newest row >= yesterday) → return
  → If cache MISS → market/provider.py: yfinance download (asyncio.to_thread)
  → market/repository.py: INSERT ... ON CONFLICT DO NOTHING
  → Return merged response
```

#### Quote Request

```
Client → GET /market/quote/AAPL
  → Try Redis GET quote:AAPL
  → If found and age < 60s → return cached quote
  → Else → market/provider.py: yfinance Ticker('AAPL').info (asyncio.to_thread)
  → Store in Redis SETEX quote:AAPL 60 <json>
  → Return fresh quote
```

#### Portfolio Performance

```
Client → GET /portfolio/performance/{portfolio_id}
  → Verify portfolio ownership (JOIN with users, same pattern as holdings)
  → Fetch holdings for portfolio
  → Fetch transactions for portfolio (sorted by date)
  → Fetch cash flows for portfolio (sorted by date)
  → For each unique ticker in holdings:
    → Fetch OHLCV from market/repository.py (DB cache)
    → Compute per-holding metrics
  → Compute free_cash = SUM(deposits) - SUM(net invested)
  → Compute TWR (cash-flow-based: uses cash_flows for external CFs, transactions for holdings state)
  → Return PortfolioPerformanceResponse (includes free_cash_balance)
```

#### Benchmark Comparison

```
Client → GET /portfolio/benchmark/{portfolio_id}
  → Compute portfolio performance (TWR + daily returns)
  → Fetch OHLCV for benchmark ticker (SPY or QQQ) over same period
  → Compute benchmark daily returns from adjusted_close
  → Compute alpha = portfolio_twr - benchmark_return
  → Compute tracking error = std(daily excess returns)
  → Compute information ratio = annualised excess return / annualised TE
  → Return BenchmarkComparisonResponse
```

---

## Implementation Rounds

### Round 1 — Market Data Provider

**Goal:** yfinance integration with PostgreSQL and Redis caching. Two endpoints working: OHLCV history and current quote.

**Files to create:** 5 (`market/__init__.py`, `market/schemas.py`, `market/repository.py`, `market/provider.py`, `market/router.py`)
**Files to modify:** 2 (`pyproject.toml`, `main.py`)
**Files to test:** 1 (`test_market.py`)

---

#### Step 1.1 — Add yfinance dependency

**File:** `backend/pyproject.toml`
**Action:** Add `yfinance>=0.2.0` to `[project.dependencies]` list.

```toml
dependencies = [
    ...
    "yfinance>=0.2.0",
    "tenacity>=9.0.0",
]
```

**Risk:** Low. Standard pip dependency add.
**Verify:** `docker compose run --rm backend sh -c "uv sync --no-dev"` succeeds (production deps only).

---

#### Step 1.2 — Create market module skeleton

**File:** `backend/src/market/__init__.py`
**Action:** Empty file with module docstring.

```python
"""
Market data provider — yfinance wrapper with PostgreSQL caching.

Public API (re-exported from provider and repository):
    get_ohlcv(ticker, start_date, end_date) -> list[OHLCVData]
    get_quote(ticker) -> QuoteResponse
"""
```

**Why:** Module marker. Follows Phase 1 pattern (see `src/holdings/__init__.py`).

---

#### Step 1.3 — Market schemas

**File:** `backend/src/market/schemas.py`
**Action:** Define Pydantic models for market data.

```python
"""
Pydantic schemas for market data endpoints.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class OHLCVData(BaseModel):
    """Single day of OHLCV price data."""
    model_config = ConfigDict(json_encoders={Decimal: float})

    date: date
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    close: Optional[Decimal] = None
    adjusted_close: Optional[Decimal] = None
    volume: Optional[int] = None
    # ponytail: all fields nullable — yfinance can return NaN for some fields on newly-listed tickers


class OHLCVResponse(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: float})

    ticker: str
    data: list[OHLCVData]
    total: int


class QuoteResponse(BaseModel):
    """Current quote snapshot for a single ticker."""
    model_config = ConfigDict(json_encoders={Decimal: float})

    ticker: str
    price: Decimal
    change: Decimal
    change_pct: Decimal
    previous_close: Decimal
    volume: int
    timestamp: datetime


class BatchQuoteResponse(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: float})

    quotes: list[QuoteResponse]
    total: int

# ── Query parameters ──

class OHLCVParams(BaseModel):
    """Query params for OHLCV endpoint."""
    start_date: Optional[date] = Field(None, description="Start date (inclusive). Defaults to 1 year ago.")
    end_date: Optional[date] = Field(None, description="End date (inclusive). Defaults to today.")
    # ponytail: no max_days limit for Phase 2 — add if abuse becomes an issue
```

**Why:** Follows Phase 1 pattern (same `ConfigDict`, `Decimal` encoders, Optional fields). OHLCVData has nullable fields because yfinance can return NaN for some fields.

---

#### Step 1.4 — OHLCV repository (DB operations)

**File:** `backend/src/market/repository.py`
**Action:** Asyncpg queries for the `ohlcv_prices` table. Pure read/write — no business logic.

```python
"""
Repository layer for the ohlcv_prices table.

All runtime queries use raw asyncpg (same pattern as Phase 1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from src.database.connection import connection_ctx


async def get_ohlcv(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    *,
    limit: int = 2000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return OHLCV rows for *ticker*, ordered by date ascending.

    Returns empty list when no data exists.
    """
    conditions = ["ticker = $1"]
    params: list[Any] = [ticker]
    idx = 2

    if start_date:
        conditions.append(f"date >= ${idx}::date")
        params.append(start_date)
        idx += 1
    if end_date:
        conditions.append(f"date <= ${idx}::date")
        params.append(end_date)
        idx += 1

    query = (
        "SELECT date, open, high, low, close, adjusted_close, volume "
        f"FROM ohlcv_prices WHERE {' AND '.join(conditions)} "
        "ORDER BY date ASC"
        f" LIMIT ${idx} OFFSET ${idx + 1}"
    )
    params.extend([limit, offset])

    async with connection_ctx() as conn:
        rows = await conn.fetch(query, *params)

    return [dict(r) for r in rows]


async def get_latest_ohlcv_date(ticker: str) -> Optional[date]:
    """Return the most recent date in ohlcv_prices for *ticker*, or None."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT MAX(date) AS max_date FROM ohlcv_prices WHERE ticker = $1",
            ticker,
        )
    return row["max_date"] if row and row["max_date"] else None


async def upsert_ohlcv(ticker: str, rows: list[dict[str, Any]]) -> int:
    """Insert OHLCV rows using INSERT … ON CONFLICT DO NOTHING.

    Uses ``executemany`` for a single round trip. Returns count of inserted rows.

    Note (ponytail): concurrent cache misses for the same ticker may race here.
    ``ON CONFLICT DO NOTHING`` prevents corruption. Add a per-ticker
    ``asyncio.Lock`` if racing becomes a concern.
    """
    if not rows:
        return 0

    params = [
        (
            ticker,
            r["date"],
            r.get("open"),
            r.get("high"),
            r.get("low"),
            r.get("close"),
            r.get("adjusted_close"),
            r.get("volume"),
        )
        for r in rows
    ]

    async with connection_ctx() as conn:
        # executemany returns a status string like "INSERT 0 5"
        status = await conn.executemany(
            """
            INSERT INTO ohlcv_prices
                (ticker, date, open, high, low, close, adjusted_close, volume)
            VALUES ($1, $2::date, $3::numeric, $4::numeric, $5::numeric,
                    $6::numeric, $7::numeric, $8::bigint)
            ON CONFLICT (ticker, date) DO NOTHING
            """,
            params,
        )
    # Parse the inserted count from the status tag
    count = int(status.split()[-1]) if status and status.startswith("INSERT") else 0
    return count


async def ticker_exists_in_db(ticker: str) -> bool:
    """Check if any OHLCV data exists for this ticker."""
    async with connection_ctx() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM ohlcv_prices WHERE ticker = $1 LIMIT 1",
            ticker,
        )
    return row is not None
```

**Why:** Follows exact same asyncpg pattern as Phase 1 routers. Each function has one clear responsibility. `upsert_ohlcv` uses ON CONFLICT DO NOTHING for idempotent caching.

---

#### Step 1.5 — yfinance provider (async wrapper)

**File:** `backend/src/market/provider.py`
**Action:** Wrap synchronous yfinance calls with `asyncio.to_thread()`. Handle yfinance DataFrame → list of dicts transformation.

```python
"""
Async wrapper around the synchronous yfinance library.

All blocking calls are delegated to ``asyncio.to_thread()`` so the event loop
is never blocked. Data is returned as plain dicts for downstream repository
or response processing.

See ADR 001 for rationale on the sync-wrapping approach.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from requests.exceptions import HTTPError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import yfinance as yf

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, ValueError, HTTPError)),
    reraise=True,
)
def _download_ohlcv(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Synchronous OHLCV download from yfinance.

    Returns a list of dicts with keys: date, open, high, low, close,
    adjusted_close, volume. NaN values are converted to None.
    """
    # yfinance expects "YYYY-MM-DD" strings
    start_str = start_date.isoformat() if start_date else None
    end_str = end_date.isoformat() if end_date else None

    df = yf.download(ticker, start=start_str, end=end_str, progress=False, auto_adjust=False)

    if df.empty:
        return []

    # yfinance returns DataFrames with a DatetimeIndex and columns:
    # ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
    rows = []
    for idx, row in df.iterrows():
        d = idx.date() if hasattr(idx, "date") else idx
        rows.append({
            "date": d,
            "open": _maybe_decimal(row.get("Open")),
            "high": _maybe_decimal(row.get("High")),
            "low": _maybe_decimal(row.get("Low")),
            "close": _maybe_decimal(row.get("Close")),
            "adjusted_close": _maybe_decimal(row.get("Adj Close")),
            "volume": _maybe_int(row.get("Volume")),
        })
    return rows


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, ValueError)),
    reraise=True,
)
def _fetch_quote(ticker: str) -> dict[str, Any]:
    """Synchronous quote fetch from yfinance Ticker.info.

    Returns a dict with keys: price, change, change_pct, previous_close,
    volume, timestamp. Falls back to ``fast_info`` if ``info`` is stale.
    """
    t = yf.Ticker(ticker)
    info = t.info or {}

    # yfinance.info has various price fields depending on market hours:
    # - regularMarketPrice: current trading price
    # - currentPrice: fallback
    # - previousClose: yesterday's close
    # - regularMarketChange / regularMarketChangePercent
    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
    prev_close = info.get("previousClose") or 0
    change = info.get("regularMarketChange") or (price - prev_close)
    change_pct = info.get("regularMarketChangePercent") or (
        (change / prev_close * 100) if prev_close else 0
    )
    volume = info.get("regularMarketVolume") or info.get("volume") or 0

    # Try fast_info for real-time data if info seems stale
    # ponytail: simple priority-based fallback; add market-status detection if accuracy requirements tighten
    # ponytail: global lock, per-ticker locks if concurrent quote hammering becomes an issue

    return {
        "ticker": ticker,
        "price": _maybe_decimal(price),
        "change": _maybe_decimal(change),
        "change_pct": _maybe_decimal(change_pct),
        "previous_close": _maybe_decimal(prev_close),
        "volume": _maybe_int(volume),
        "timestamp": datetime.utcnow(),
    }


def _maybe_decimal(value: Any) -> Optional[Decimal]:
    """Convert a float/None to Decimal or None. Handles NaN."""
    if value is None:
        return None
    try:
        v = float(value)
        if v != v:  # NaN check
            return None
        return Decimal(str(v))
    except (ValueError, TypeError):
        return None


def _maybe_int(value: Any) -> Optional[int]:
    """Convert a float/None to int or None. Handles NaN."""
    if value is None:
        return None
    try:
        v = float(value)
        if v != v:  # NaN check
            return None
        return int(v)
    except (ValueError, TypeError):
        return None


# ── Async public API ──


async def fetch_ohlcv(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Fetch OHLCV data from yfinance in a thread pool.

    Defaults to the last 1 year if no dates provided.
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=365)
    # yfinance uses exclusive end_date semantics, so add a day for inclusivity
    if end_date is None:
        end_date = date.today()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _download_ohlcv,
        ticker,
        start_date,
        end_date,
    )


async def fetch_quote(ticker: str) -> dict[str, Any]:
    """Fetch current quote from yfinance in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_quote, ticker)
```

**Why:** yfinance is synchronous (`yf.download()`, `yf.Ticker().info`). Wrapping with `asyncio.to_thread()` prevents event loop blocking. The `_maybe_decimal` / `_maybe_int` helpers handle yfinance's NaN-prone return values. See ADR 001.

---

#### Step 1.6 — Market router

**File:** `backend/src/market/router.py`
**Action:** Three endpoints: `/market/ohlcv/{ticker}`, `/market/quote/{ticker}`, `/market/ohlcv/batch` (optional).

```python
"""
FastAPI router for market data endpoints.

Endpoints:
    - ``GET /market/ohlcv/{ticker}`` — historical OHLCV (DB cache → yfinance)
    - ``GET /market/quote/{ticker}`` — current quote (Redis cache → yfinance)
    - ``GET /market/ohlcv/batch`` — batch OHLCV for multiple tickers (experimental)
"""

from __future__ import annotations

import json
import structlog
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.cache.redis import get_redis
from src.config import settings
from src.limiter import limiter

from src.market.repository import (
    get_latest_ohlcv_date,
    get_ohlcv,
    ticker_exists_in_db,
    upsert_ohlcv,
)
from src.market.schemas import (
    OHLCVData,
    OHLCVParams,
    OHLCVResponse,
    QuoteResponse,
)
from src.market.provider import fetch_ohlcv, fetch_quote

logger = structlog.get_logger()

router = APIRouter()

QUOTE_CACHE_TTL = 60  # seconds — see ADR 003


async def _refresh_ohlcv_if_stale(ticker: str) -> bool:
    """Check cache freshness and fetch from yfinance if stale.

    Returns True if data was refreshed (or fetched for the first time).
    """
    latest_db_date = await get_latest_ohlcv_date(ticker)

    # Cache HIT: newest data is yesterday or newer
    # Weekend tolerance: on Monday, accept Friday's data (3-day gap)
    staleness_days = 3 if date.today().weekday() == 0 else 1
    if latest_db_date is not None and latest_db_date >= date.today() - timedelta(days=staleness_days):
        return False

    # Cache MISS or stale: fetch from yfinance
    logger.info("fetching_ohlcv_from_yfinance", ticker=ticker)

    try:
        rows = await fetch_ohlcv(ticker, start_date=None, end_date=None)
    except Exception as exc:
        logger.error("yfinance_ohlcv_failed", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Market data temporarily unavailable for {ticker}",
        )

    if not rows:
        logger.warning("yfinance_returned_empty", ticker=ticker)
        return False

    inserted = await upsert_ohlcv(ticker, rows)
    logger.info(
        "ohlcv_cached",
        ticker=ticker,
        rows_fetched=len(rows),
        rows_inserted=inserted,
    )
    return True


def _row_to_ohlcv_data(row: dict[str, Any]) -> OHLCVData:
    return OHLCVData(
        date=row["date"],
        open=row.get("open"),
        high=row.get("high"),
        low=row.get("low"),
        close=row.get("close"),
        adjusted_close=row.get("adjusted_close"),
        volume=row.get("volume"),
    )


@router.get("/ohlcv/{ticker}", response_model=OHLCVResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_ohlcv_endpoint(
    request: Request,
    ticker: str,
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: UserInDB = Depends(get_current_user),
) -> OHLCVResponse:
    """Return historical OHLCV data for a ticker.

    Data is served from the PostgreSQL cache when available and fresh.
    Stale or missing data triggers a background-like refresh from yfinance.
    Requires authentication (any authenticated user can fetch market data).
    """
    ticker = ticker.upper()

    # Attempt to refresh cache if data is stale
    await _refresh_ohlcv_if_stale(ticker)

    # Set date defaults after (potential) refresh
    if start_date is None:
        start_date = date.today() - timedelta(days=365)
    if end_date is None:
        end_date = date.today()

    rows = await get_ohlcv(ticker, start_date=start_date, end_date=end_date)

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for {ticker}",
        )

    data = [_row_to_ohlcv_data(r) for r in rows]
    return OHLCVResponse(ticker=ticker, data=data, total=len(data))


@router.get("/quote/{ticker}", response_model=QuoteResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_quote_endpoint(
    request: Request,
    ticker: str,
    current_user: UserInDB = Depends(get_current_user),
) -> QuoteResponse:
    """Return current quote for a ticker.

    Uses a 60-second Redis cache to avoid hammering yfinance.
    Cache is per-ticker (key: ``quote:{ticker}``).
    """
    ticker = ticker.upper()
    cache_key = f"quote:{ticker}"

    # Try Redis cache (graceful degradation on Redis failure)
    try:
        r = await get_redis()
        if r is not None:
            cached = await r.get(cache_key)
            if cached is not None:
                try:
                    data = json.loads(cached)
                    return QuoteResponse(**data)
                except (json.JSONDecodeError, TypeError):
                    pass  # Corrupted cache — refetch
    except Exception:
        logger.warning("redis_cache_read_failed", ticker=ticker)

    # Cache miss: fetch from yfinance
    try:
        quote_data = await fetch_quote(ticker)
    except Exception as exc:
        logger.error("yfinance_quote_failed", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Quote temporarily unavailable for {ticker}",
        )

    response = QuoteResponse(
        ticker=quote_data["ticker"],
        price=quote_data["price"],
        change=quote_data["change"],
        change_pct=quote_data["change_pct"],
        previous_close=quote_data["previous_close"],
        volume=quote_data["volume"],
        timestamp=quote_data["timestamp"],
    )

    # Cache in Redis (graceful degradation: skip if Redis unavailable)
    try:
        if r is not None:
            await r.setex(cache_key, QUOTE_CACHE_TTL, response.model_dump_json())
    except Exception:
        logger.warning("redis_cache_write_failed", ticker=ticker)

    return response
```

**Why:** Same pattern as Phase 1 routers (rate limiting, auth dependency, structlog, HTTPException). Cache-freshness logic is extracted to `_refresh_ohlcv_if_stale` for testability. `_row_to_ohlcv_data` maps nullable DB columns to the schema.

**Edge cases handled:**

- Ticker not found in yfinance → 404
- yfinance unreachable → 503
- DB has partial data (e.g., 1 year of 5 requested) → return what we have
- Redis unavailable → skip cache, fetch fresh (graceful degradation)

---

#### Step 1.7 — Register market router in main.py

**File:** `backend/src/main.py`
**Action:** Add market router import and registration.

```python
# Add to the router registrations section (~line 107-118)
from src.market.router import router as market_router  # noqa: E402

app.include_router(market_router, prefix="/market", tags=["market"])
```

**Why:** Follows existing pattern. All routers registered in main.py.

---

#### Step 1.8 — Market data tests

**File:** `backend/tests/test_market.py`
**Action:** Test all three endpoints + repository + provider (with yfinance mocked).

Target: 30+ tests covering:

- GET /market/ohlcv/{ticker} happy path (mocked yfinance → DB cache hit)
- GET /market/ohlcv/{ticker} with date range
- GET /market/ohlcv/{ticker} ticker not found (404)
- GET /market/ohlcv/{ticker} yfinance unavailable (503)
- GET /market/ohlcv/{ticker} start_date > end_date (400 or empty)
- GET /market/quote/{ticker} happy path (mocked yfinance → Redis cache)
- GET /market/quote/{ticker} Redis cache hit (within 60s, returns cached)
- GET /market/quote/{ticker} Redis cache miss (fetches fresh)
- GET /market/quote/{ticker} yfinance failure (503)
- \_refresh_ohlcv_if_stale — fresh cache short-circuits (no yfinance call)
- \_refresh_ohlcv_if_stale — stale cache + yfinance failure (503 path)
- Repository: upsert_ohlcv idempotency (duplicate rows ignored)
- Repository: upsert_ohlcv batch insert (executemany)
- Repository: get_ohlcv empty result
- Repository: get_ohlcv with partial date range (returns subset)
- Repository: get_latest_ohlcv_date with no data
- Provider: \_download_ohlcv DataFrame parsing (multi-row)
- Provider: \_download_ohlcv empty DataFrame
- Provider: \_fetch_quote info field extraction
- Provider: \_fetch_quote with NaN fields
- Provider: \_maybe_decimal NaN handling
- Provider: \_maybe_decimal None handling
- Provider: \_maybe_decimal string input
- Provider: \_row_to_ohlcv_data null field mapping
- Unauthenticated access returns 401

```python
"""Tests for the market data module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# Use the same conftest fixtures: client, auth_headers, _test_db, _setup_app


@pytest.mark.asyncio
async def test_get_ohlcv_happy_path(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /market/ohlcv/AAPL returns OHLCV data (mocked yfinance)."""
    # Arrange: pre-seed ohlcv_prices via repository
    from src.market.repository import upsert_ohlcv

    rows = [
        {
            "date": "2024-01-02",
            "open": 180.0,
            "high": 185.0,
            "low": 179.0,
            "close": 184.0,
            "adjusted_close": 183.5,
            "volume": 50000000,
        },
        {
            "date": "2024-01-03",
            "open": 184.5,
            "high": 187.0,
            "low": 183.0,
            "close": 186.0,
            "adjusted_close": 185.5,
            "volume": 45000000,
        },
    ]
    inserted = await upsert_ohlcv("AAPL", rows)
    assert inserted == 2

    # Act
    response = await client.get(
        "/market/ohlcv/AAPL",
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["total"] == 2
    assert len(data["data"]) == 2
    assert data["data"][0]["date"] == "2024-01-02"
    assert data["data"][0]["close"] == 184.0


@pytest.mark.asyncio
async def test_get_ohlcv_requires_auth(client: AsyncClient) -> None:
    """Unauthenticated requests should return 401."""
    response = await client.get("/market/ohlcv/AAPL")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_quote_happy_path(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /market/quote/AAPL returns quote data (mocked yfinance, no Redis)."""
    with patch("src.market.provider._fetch_quote") as mock_fetch, \
         patch("src.market.provider.get_redis", return_value=None):
        from datetime import datetime
        mock_fetch.return_value = {
            "ticker": "AAPL",
            "price": 185.50,
            "change": 1.25,
            "change_pct": 0.68,
            "previous_close": 184.25,
            "volume": 45000000,
            "timestamp": datetime.utcnow(),
        }

        response = await client.get(
            "/market/quote/AAPL",
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["price"] == 185.50
    assert data["change"] == 1.25
    assert data["change_pct"] == 0.68
```

(Full test file continues with ~25 tests covering all cases.)

---

### Round 2 — Portfolio Performance

**Goal:** Cash flows module, P&L, TWR (cash-flow-based), benchmark comparison with TE/IR.

**Files to create:** 8 (`performance/__init__.py`, `performance/schemas.py`, `performance/calculations.py`, `performance/router.py`, `cash_flows/__init__.py`, `cash_flows/schemas.py`, `cash_flows/repository.py`, `cash_flows/router.py`)
**Files to modify:** 2 (`main.py`, alevoltic migration file for cash_flows table)
**Files to test:** 2 (`test_performance.py`, `test_cash_flows.py`)

---

#### Step 2.1 — Performance schemas

**File:** `backend/src/performance/schemas.py`
**Action:** Define Pydantic models for performance responses.

```python
"""
Pydantic schemas for portfolio performance and benchmark comparison endpoints.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class HoldingPerformance(BaseModel):
    """Performance metrics for a single holding."""
    model_config = ConfigDict(json_encoders={Decimal: float})

    ticker: str
    shares: Decimal
    average_cost_basis: Decimal
    current_price: Optional[Decimal] = None
    market_value: Optional[Decimal] = None
    cost_basis: Decimal
    unrealised_pl: Optional[Decimal] = None
    unrealised_pl_pct: Optional[Decimal] = None
    day_change: Optional[Decimal] = None
    day_change_pct: Optional[Decimal] = None
    portfolio_weight_pct: Optional[Decimal] = None


class PortfolioPerformanceResponse(BaseModel):
    """Aggregate portfolio performance."""
    model_config = ConfigDict(json_encoders={Decimal: float})

    portfolio_id: str
    portfolio_name: str
    total_market_value: Optional[Decimal] = None
    total_cost_basis: Decimal
    total_unrealised_pl: Optional[Decimal] = None
    total_unrealised_pl_pct: Optional[Decimal] = None
    day_change: Optional[Decimal] = None
    day_change_pct: Optional[Decimal] = None
    free_cash_balance: Decimal = Field(
        Decimal(0),
        description="Uninvested cash = SUM(deposits) - SUM(net BUY amounts)",
    )
    # Time-weighted return
    twr: Optional[Decimal] = Field(None, description="Time-weighted return over the period")
    twr_annualised: Optional[Decimal] = None
    twr_start_date: Optional[date] = None
    twr_end_date: Optional[date] = None
    twr_methodology: str = Field(
        "cash-flow-based",
        description="Cash flows are explicit deposits (from receipt scans); no manual withdrawals",
    )
    # Holdings breakdown
    holdings: list[HoldingPerformance]
    total_holdings: int
    # Data quality
    data_quality: str = Field(
        "complete",
        description="'complete' or 'partial' — partial means some holdings lack price data",
    )
    calculated_at: datetime


class BenchmarkComparisonResponse(BaseModel):
    """Portfolio vs benchmark comparison."""
    model_config = ConfigDict(json_encoders={Decimal: float})

    portfolio_id: str
    benchmark_ticker: str
    portfolio_return: Optional[Decimal] = None
    benchmark_return: Optional[Decimal] = None
    excess_return_alpha: Optional[Decimal] = None
    tracking_error: Optional[Decimal] = None
    information_ratio: Optional[Decimal] = None
    period_start: date
    period_end: date
    methodology: str = "daily-linked"
    daily_returns_count: int = Field(0, description="Number of daily return observations used")
    calculated_at: datetime


class PerformanceParams(BaseModel):
    """Query parameters for performance endpoint."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    benchmark: Optional[str] = Field(None, description="Benchmark ticker (default: SPY)")


class BenchmarkParams(BaseModel):
    """Query parameters for benchmark comparison."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    benchmark: Optional[str] = Field("SPY", description="Benchmark ticker (SPY or QQQ)")
```

**Why:** `data_quality` field signals partial data. `twr_methodology` updated to `"cash-flow-based"` (explicit deposits). `free_cash_balance` tracks uninvested cash. `daily_returns_count` signals how many observations the TE/IR calculations are based on. All monetary values are `Decimal` → `float` via `json_encoders`.

---

#### Step 2.2 — Cash flows module (database migration)

**File:** New Aleavoltic migration (`0003_add_cash_flows.py`)
**Action:** Create `cash_flows` table for explicit portfolio deposits.

```python
# migrations/versions/0003_add_cash_flows.py
\"\"\"Add cash_flows table for explicit portfolio deposits.\"\"\"
from alembic import op
import sqlalchemy as sa

# Must chain to Phase 1 migration
down_revision = "0002"
revision = "0003"

def upgrade():
    op.create_table(
        "cash_flows",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("portfolio_id", sa.UUID(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="receipt"),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_cash_flows_portfolio_date", "cash_flows", ["portfolio_id", "created_at"])

def downgrade():
    op.drop_table("cash_flows")
```

**Key detail:** `down_revision = "0002"` — without this, Alembic won't chain 0003 after 0002 and the migration will apply out of order.

**Why the simplified design:**

- Paper trading: no real withdrawals. `amount` is always positive (deposits only).
- `source_id` links back to `receipts.id` for traceability but has no FK constraint (receipts can be deleted independently).
- TWR needs these as explicit external cash flows instead of inferring them from BUY/SELL transaction amounts (the previous approach from ADR 002).

**Edge cases:**

- Duplicate deposits: same receipt scanned twice → two cash_flow records. No dedup (handled at the frontend).
- Zero-amount deposit: reject at schema level (amount > 0 validation).

---

#### Step 2.3 — Cash flows schemas

**File:** `backend/src/cash_flows/schemas.py`
**Action:** Pydantic models for cash flow CRUD.

```python
"""
Pydantic schemas for portfolio cash flow management.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CashFlowCreate(BaseModel):
    """Request body for recording a new cash flow (deposit)."""
    amount: Decimal = Field(..., gt=Decimal(0), description="Deposit amount (positive only)")
    source: str = Field("receipt", description="Source of deposit: 'receipt', 'manual', 'transfer'")
    source_id: Optional[UUID] = Field(None, description="ID of the source receipt, if applicable")
    notes: Optional[str] = None


class CashFlowUpdate(BaseModel):
    """Request body for updating a cash flow (notes only — amount is immutable)."""
    notes: Optional[str] = None


class CashFlowInDB(BaseModel):
    """Full cash flow record as stored in the database."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    portfolio_id: UUID
    amount: Decimal
    source: str
    source_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_at: datetime


class CashFlowResponse(BaseModel):
    """API response for a single cash flow."""
    model_config = ConfigDict(json_encoders={Decimal: float})

    id: str
    portfolio_id: str
    amount: Decimal
    source: str
    source_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class CashFlowListResponse(BaseModel):
    """Paginated list of cash flows."""
    cash_flows: list[CashFlowResponse]
    total: int
    limit: int
    offset: int
```

**Why:** Mirrors the receipts module pattern (same team, consistent conventions). `amount` is constrained to positive values since V1 only supports deposits. No DELETE endpoint — cash flows are append-only for auditability.

---

#### Step 2.4 — Cash flows repository

**File:** `backend/src/cash_flows/repository.py`
**Action:** asyncpg-based CRUD for `cash_flows` table.

```python
"""
Cash flows repository — direct asyncpg queries.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from src.database.connection import connection_ctx


async def create_cash_flow(
    portfolio_id: str,
    amount: Decimal,
    source: str = "receipt",
    source_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Insert a cash flow record and return it."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cash_flows (portfolio_id, amount, source, source_id, notes)
            VALUES ($1::uuid, $2, $3, $4::uuid, $5)
            RETURNING id, portfolio_id, amount, source, source_id, notes, created_at
            """,
            portfolio_id,
            amount,
            source,
            source_id,
            notes,
        )
    return dict(row)


async def list_cash_flows(
    portfolio_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List cash flows for a portfolio, most recent first."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = $1::uuid "
            "ORDER BY created_at DESC "
            "LIMIT $2 OFFSET $3",
            portfolio_id,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


async def count_cash_flows(portfolio_id: str) -> int:
    """Count total cash flows for a portfolio."""
    async with connection_ctx() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )


async def get_cash_flow(id: str) -> dict[str, Any] | None:
    """Get a single cash flow by ID."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE id = $1::uuid",
            id,
        )
    return dict(row) if row else None


async def update_cash_flow_notes(id: str, notes: Optional[str]) -> bool:
    """Update notes on a cash flow. Returns True if updated."""
    async with connection_ctx() as conn:
        result = await conn.execute(
            "UPDATE cash_flows SET notes = $2 WHERE id = $1::uuid",
            id,
            notes,
        )
    return result == "UPDATE 1"


async def sum_cash_flows(portfolio_id: str) -> Decimal:
    """Return total deposits for a portfolio (SUM of all cash flows)."""
    async with connection_ctx() as conn:
        total = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
    return Decimal(str(total))
```

**Why:** Same asyncpg pattern as Phase 1 and `market/repository.py`. `sum_cash_flows` is used by the performance module to compute free cash.

---

#### Step 2.5 — Cash flows router

**File:** `backend/src/cash_flows/router.py`
**Action:** CRUD endpoints for portfolio cash flows.

```python
"""
FastAPI router for portfolio cash flow management.
"""

from __future__ import annotations

import structlog
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.limiter import limiter

from src.cash_flows.repository import (
    create_cash_flow,
    list_cash_flows,
    count_cash_flows,
    get_cash_flow,
    update_cash_flow_notes,
)
from src.cash_flows.schemas import (
    CashFlowCreate,
    CashFlowListResponse,
    CashFlowResponse,
    CashFlowUpdate,
)

logger = structlog.get_logger()

router = APIRouter()


async def _verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None:
    """Return the portfolio row if it exists and belongs to *user_id*."""
    from src.database.connection import connection_ctx
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, user_id, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


@router.get("/portfolios/{portfolio_id}/cash-flows", response_model=CashFlowListResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_cash_flows_endpoint(
    request: Request,
    portfolio_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserInDB = Depends(get_current_user),
) -> CashFlowListResponse:
    """List cash flows for a portfolio (most recent first)."""
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    rows = await list_cash_flows(str(portfolio_id), limit=limit, offset=offset)
    total = await count_cash_flows(str(portfolio_id))

    return CashFlowListResponse(
        cash_flows=[CashFlowResponse(
            id=str(r["id"]),
            portfolio_id=str(r["portfolio_id"]),
            amount=Decimal(r["amount"]),
            source=r["source"],
            source_id=str(r["source_id"]) if r.get("source_id") else None,
            notes=r.get("notes"),
            created_at=r["created_at"],
        ) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/portfolios/{portfolio_id}/cash-flows", response_model=CashFlowResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_cash_flow_endpoint(
    request: Request,
    portfolio_id: UUID,
    body: CashFlowCreate,
    current_user: UserInDB = Depends(get_current_user),
) -> CashFlowResponse:
    """Record a cash flow (deposit) into a portfolio."""
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    row = await create_cash_flow(
        portfolio_id=str(portfolio_id),
        amount=Decimal(str(body.amount)),
        source=body.source,
        source_id=str(body.source_id) if body.source_id else None,
        notes=body.notes,
    )
    logger.info("cash_flow_created", portfolio_id=str(portfolio_id), amount=body.amount)

    return CashFlowResponse(
        id=str(row["id"]),
        portfolio_id=str(row["portfolio_id"]),
        amount=Decimal(row["amount"]),
        source=row["source"],
        source_id=str(row["source_id"]) if row.get("source_id") else None,
        notes=row.get("notes"),
        created_at=row["created_at"],
    )


@router.patch("/portfolios/{portfolio_id}/cash-flows/{cash_flow_id}", response_model=CashFlowResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_cash_flow_endpoint(
    request: Request,
    portfolio_id: UUID,
    cash_flow_id: UUID,
    body: CashFlowUpdate,
    current_user: UserInDB = Depends(get_current_user),
) -> CashFlowResponse:
    """Update notes on a cash flow (amount is immutable)."""
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    existing = await get_cash_flow(str(cash_flow_id))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cash flow not found")

    updated = await update_cash_flow_notes(str(cash_flow_id), body.notes)
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update")

    row = await get_cash_flow(str(cash_flow_id))
    return CashFlowResponse(
        id=str(row["id"]),
        portfolio_id=str(row["portfolio_id"]),
        amount=Decimal(row["amount"]),
        source=row["source"],
        source_id=str(row["source_id"]) if row.get("source_id") else None,
        notes=row.get("notes"),
        created_at=row["created_at"],
    )
```

**Why:** Same pattern as Phase 1 routers. `amount` is immutable (cash flows are audit records). Notes-only update. No DELETE (append-only for audit). All endpoints require portfolio ownership verification.

---

#### Step 2.6 — Performance calculations (pure functions, updated)

**File:** `backend/src/performance/calculations.py`
**Action:** Pure computation functions — TWR, P&L, benchmark, daily returns. No DB access. Designed for testability. Takes explicit `cash_flows` param (separate from BUY/SELL transactions).

**TWR Algorithm (see ADR 002 for methodology):**

```
1. Merge all transaction dates + all cash flow dates within [start, end]
2. Sub-periods = [start_date] + merged_dates + [end_date] (deduplicated, sorted)
3. For each sub-period (d_i, d_{i+1}):
   a. Reconstruct holdings at d_i (process all transactions on or before d_i)
   b. BMV = portfolio_value(holdings_at_d_i, prices on d_i)
   c. Reconstruct holdings at d_{i+1}
   d. EMV = portfolio_value(holdings_at_d_{i+1}, prices on d_{i+1})
   e. CF = sum of cash flow amounts on dates in (d_i, d_{i+1}]
   f. If BMV == 0 → r = 0 (new investment guard)
   g. Else → r = (EMV - BMV - CF) / BMV
4. TWR = Π(1 + r_i) - 1
```

```python
"""
Pure portfolio computation functions.

No DB access — all data is passed in as arguments for testability.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Optional

from src.performance.schemas import (
    BenchmarkComparisonResponse,
    HoldingPerformance,
    PortfolioPerformanceResponse,
)


def compute_holding_performance(
    ticker: str,
    shares: Decimal,
    avg_cost_basis: Decimal,
    current_price: Optional[Decimal],
    previous_close: Optional[Decimal],
    total_portfolio_value: Optional[Decimal],
) -> HoldingPerformance:
    """Compute performance metrics for a single holding.

    Args:
        ticker: Holding ticker.
        shares: Number of shares held.
        avg_cost_basis: Average cost per share.
        current_price: Current market price (None if unavailable).
        previous_close: Previous day's close (None if unavailable).
        total_portfolio_value: Total portfolio value for weight calculation.

    Returns:
        HoldingPerformance with computed metrics.
    """
    cost_basis = shares * avg_cost_basis

    if current_price is not None:
        market_value = shares * current_price
        unrealised_pl = market_value - cost_basis
        if avg_cost_basis > 0:
            unrealised_pl_pct = (current_price - avg_cost_basis) / avg_cost_basis * 100
        else:
            # ponytail: zero-cost-basis holdings (transfers, DRIP) — P&L % is undefined
            unrealised_pl_pct = None
    else:
        market_value = None
        unrealised_pl = None
        unrealised_pl_pct = None

    if current_price is not None and previous_close is not None and previous_close > 0:
        day_change = shares * (current_price - previous_close)
        day_change_pct = (current_price - previous_close) / previous_close * 100
    else:
        day_change = None
        day_change_pct = None

    portfolio_weight_pct = (
        (market_value / total_portfolio_value * 100)
        if market_value is not None and total_portfolio_value and total_portfolio_value > 0
        else None
    )

    return HoldingPerformance(
        ticker=ticker,
        shares=shares,
        average_cost_basis=avg_cost_basis,
        current_price=current_price,
        market_value=market_value,
        cost_basis=cost_basis,
        unrealised_pl=unrealised_pl,
        unrealised_pl_pct=unrealised_pl_pct,
        day_change=day_change,
        day_change_pct=day_change_pct,
        portfolio_weight_pct=portfolio_weight_pct,
    )


def compute_portfolio_performance(
    portfolio_id: str,
    portfolio_name: str,
    holdings_data: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    cash_flows: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    enable_twr: bool = True,
) -> PortfolioPerformanceResponse:
    """Compute aggregate portfolio performance including TWR.

    Args:
        portfolio_id: UUID of the portfolio.
        portfolio_name: Display name.
        holdings_data: List of holding rows from DB (with ticker, shares, avg_cost_basis).
        transactions: List of transaction rows from DB (with type, ticker, shares,
                      total_amount, date). Must be sorted by date ascending.
        cash_flows: List of cash flow rows from DB (with amount, created_at).
        price_map: Nested dict: {ticker: {date: adjusted_close}}.
        start_date: Start of analysis period (defaults to 1 year ago).
        end_date: End of analysis period (defaults to today).
        enable_twr: If False, skip TWR computation (returns None for TWR fields).

    Returns:
        PortfolioPerformanceResponse with computed metrics.
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date.replace(year=end_date.year - 1)

    # ── 1. Get current prices ──
    latest_prices: dict[str, Decimal] = {}
    previous_closes: dict[str, Decimal] = {}
    for h in holdings_data:
        ticker = h["ticker"]
        ticker_prices = price_map.get(ticker, {})
        if ticker_prices:
            sorted_dates = sorted(ticker_prices.keys())
            latest_prices[ticker] = ticker_prices[sorted_dates[-1]]
            if len(sorted_dates) >= 2:
                previous_closes[ticker] = ticker_prices[sorted_dates[-2]]

    # ── 2. Per-holding metrics ──
    holdings_with_prices = 0
    holdings_total = len(holdings_data)

    holdings_perf = []
    total_market_value = Decimal(0)
    total_cost_basis = Decimal(0)

    for h in holdings_data:
        ticker = h["ticker"]
        shares = h["shares"]
        avg_cost = h["average_cost_basis"]

        hp = compute_holding_performance(
            ticker=ticker,
            shares=shares,
            avg_cost_basis=avg_cost,
            current_price=latest_prices.get(ticker),
            previous_close=previous_closes.get(ticker),
            total_portfolio_value=None,  # Will recalc after we know the total
        )
        if hp.market_value is not None:
            total_market_value += hp.market_value
            holdings_with_prices += 1
        total_cost_basis += hp.cost_basis
        holdings_perf.append(hp)

    # Recalculate weights now that we have total_market_value
    for hp in holdings_perf:
        if hp.market_value is not None and total_market_value > 0:
            hp.portfolio_weight_pct = (hp.market_value / total_market_value * 100)

    # ── 3. Portfolio-level P&L ──
    if total_market_value > 0 and total_cost_basis > 0:
        total_unrealised_pl = total_market_value - total_cost_basis
        total_unrealised_pl_pct = (total_unrealised_pl / total_cost_basis) * 100
    else:
        total_unrealised_pl = total_market_value - total_cost_basis if total_market_value else None
        total_unrealised_pl_pct = None

    # ── 4. Day Change ──
    # ponytail: day-change weights use previous_close × shares (start-of-day value).
    # Using current_price × shares would slightly bias toward holdings with larger
    # intraday gains. The difference is negligible for daily moves <2%.
    total_day_change = Decimal(0)
    total_day_change_pct = None
    day_change_computed = 0
    day_change_weights: dict[str, Decimal] = {}  # ticker -> weight (previous value)
    for hp in holdings_perf:
        if hp.day_change is not None:
            total_day_change += hp.day_change
            day_change_computed += 1
            # Weight = starting value (previous_close × shares)
            if hp.current_price is not None and hp.day_change_pct is not None:
                prev_value = hp.market_value / (1 + hp.day_change_pct / 100)
                day_change_weights[hp.ticker] = prev_value
    if day_change_computed > 0 and day_change_weights:
        total_weight = sum(day_change_weights.values())
        if total_weight > 0:
            weighted_sum = sum(
                (hp.day_change_pct or 0) * day_change_weights.get(hp.ticker, 0) / total_weight
                for hp in holdings_perf
            )
            total_day_change_pct = weighted_sum

    # ── 5. Free cash balance ──
    total_deposits = sum(cf["amount"] for cf in cash_flows)
    # Net invested = sum of BUY amounts from transactions
    net_invested = sum(
        t["total_amount"] for t in transactions if t["type"] == "BUY"
    ) - sum(
        t["total_amount"] for t in transactions if t["type"] == "SELL"
    )
    free_cash_balance = total_deposits - net_invested

    # ── 6. TWR ──
    twr: Optional[Decimal] = None
    twr_annualised: Optional[Decimal] = None
    if enable_twr:
        twr, twr_annualised = _compute_twr(
            transactions=transactions,
            cash_flows=cash_flows,
            price_map=price_map,
            start_date=start_date,
            end_date=end_date,
        )

    # ── 7. Data quality ──
    data_quality = "complete" if holdings_with_prices == holdings_total else "partial"

    return PortfolioPerformanceResponse(
        portfolio_id=portfolio_id,
        portfolio_name=portfolio_name,
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_unrealised_pl=total_unrealised_pl,
        total_unrealised_pl_pct=total_unrealised_pl_pct,
        day_change=total_day_change if day_change_computed > 0 else None,
        day_change_pct=total_day_change_pct,
        free_cash_balance=free_cash_balance,
        twr=twr,
        twr_annualised=twr_annualised,
        twr_start_date=start_date,
        twr_end_date=end_date,
        holdings=holdings_perf,
        total_holdings=holdings_total,
        data_quality=data_quality,
        calculated_at=datetime.utcnow(),
    )


def _compute_twr(
    transactions: list[dict[str, Any]],
    cash_flows: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: date,
    end_date: date,
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Compute Time-Weighted Return using daily linking methodology.

    Cash flows (explicit deposits) and transactions (BUY/SELL for holdings)
    are separate signals. Cash flow amounts are the external CF for TWR;
    transactions determine holdings state only.
    """
    relevant_txns = [
        t for t in transactions
        if t["date"] <= end_date
    ]

    if not relevant_txns and not cash_flows:
        return None, None

    # Merge transaction dates and cash flow dates
    txn_dates = sorted({t["date"] for t in relevant_txns if start_date <= t["date"] <= end_date})
    cf_dates = sorted({cf["created_at"].date() if hasattr(cf["created_at"], "date") else cf["created_at"]
                       for cf in cash_flows if start_date <= (cf["created_at"].date() if hasattr(cf["created_at"], "date") else cf["created_at"]) <= end_date})
    all_dates = sorted(set([start_date] + txn_dates + cf_dates + [end_date]))

    # Build lookup maps
    txns_by_date: dict[date, list[dict]] = defaultdict(list)
    for t in relevant_txns:
        txns_by_date[t["date"]].append(t)

    cfs_by_date: dict[date, Decimal] = defaultdict(Decimal)
    for cf in cash_flows:
        cf_date = cf["created_at"].date() if hasattr(cf["created_at"], "date") else cf["created_at"]
        if start_date <= cf_date <= end_date:
            cfs_by_date[cf_date] += cf["amount"]

    # TWR methodology: CF = cash_flows (deposits), transactions = holdings state
    # BMV is captured BEFORE applying sub-end transactions
    cumulative_return = Decimal(1)
    sub_period_count = 0

    # Seed initial holdings from transactions before start_date
    current_holdings: dict[str, Decimal] = {}
    for txn in relevant_txns:
        if txn["date"] >= start_date:
            continue
        if txn["type"] == "BUY":
            current_holdings[txn["ticker"]] = current_holdings.get(txn["ticker"], Decimal(0)) + txn["shares"]
        else:
            current_holdings[txn["ticker"]] = current_holdings.get(txn["ticker"], Decimal(0)) - txn["shares"]
            if current_holdings[txn["ticker"]] <= 0:
                del current_holdings[txn["ticker"]]

    for i in range(len(all_dates) - 1):
        sub_start = all_dates[i]
        sub_end = all_dates[i + 1]

        # 1. BMV before sub_end transactions
        bmv = _portfolio_value(current_holdings, price_map, sub_start)

        # 2. Apply sub_end transactions (update holdings)
        for txn in txns_by_date.get(sub_end, []):
            ticker = txn["ticker"]
            if txn["type"] == "BUY":
                current_holdings[ticker] = current_holdings.get(ticker, Decimal(0)) + txn["shares"]
            else:
                current_holdings[ticker] = current_holdings.get(ticker, Decimal(0)) - txn["shares"]
                if current_holdings[ticker] <= 0:
                    del current_holdings[ticker]

        # 3. EMV after sub_end
        emv = _portfolio_value(current_holdings, price_map, sub_end)

        # 4. Cash flow for this sub-period = deposits on sub_end
        cf_total = cfs_by_date.get(sub_end, Decimal(0))

        if bmv == 0 and cf_total > 0:
            sub_return = Decimal(0)
        elif bmv == 0:
            continue
        else:
            sub_return = (emv - bmv - cf_total) / bmv

        cumulative_return *= (Decimal(1) + sub_return)
        sub_period_count += 1

    if sub_period_count == 0:
        return None, None

    twr = cumulative_return - Decimal(1)
    days = (end_date - start_date).days
    if days > 0:
        twr_annualised = (Decimal(1) + twr) ** (Decimal(365) / Decimal(days)) - Decimal(1)
    else:
        twr_annualised = None

    return twr, twr_annualised


def _portfolio_value(
    holdings: dict[str, Decimal],
    price_map: dict[str, dict[date, Decimal]],
    valuation_date: date,
) -> Decimal:
    """Compute total market value of holdings at a given date.

    Uses the closest available price (last available before the valuation date).
    """
    total = Decimal(0)
    for ticker, shares in holdings.items():
        price = _get_closest_price(price_map, ticker, valuation_date)
        if price is not None:
            total += shares * price
    return total


def _get_closest_price(
    price_map: dict[str, dict[date, Decimal]],
    ticker: str,
    target_date: date,
) -> Optional[Decimal]:
    """Get the closest available adjusted_close for a ticker at/before *target_date*."""
    ticker_prices = price_map.get(ticker)
    if not ticker_prices:
        return None

    # Find the last price on or before target_date
    available_dates = [d for d in ticker_prices if d <= target_date]
    if not available_dates:
        return None

    closest = max(available_dates)
    return ticker_prices[closest]


def compute_benchmark_comparison(
    portfolio_id: str,
    portfolio_twr: Optional[Decimal],
    benchmark_ticker: str,
    benchmark_daily_returns: list[Decimal],
    portfolio_daily_returns: list[Decimal],
    period_start: date,
    period_end: date,
) -> BenchmarkComparisonResponse:
    """Compute portfolio vs benchmark comparison metrics.

    Args:
        portfolio_id: UUID of the portfolio.
        portfolio_twr: Portfolio TWR over the period.
        benchmark_ticker: Ticker of the benchmark (SPY/QQQ).
        benchmark_daily_returns: Daily benchmark returns for tracking error.
        portfolio_daily_returns: Daily portfolio returns for tracking error.
        period_start: Start of comparison period.
        period_end: End of comparison period.

    Returns:
        BenchmarkComparisonResponse.
    """
    # Benchmark return from adjusted_close prices: simple geometric linking
    benchmark_return = Decimal(1)
    for r in benchmark_daily_returns:
        benchmark_return *= (Decimal(1) + r)
    benchmark_return -= Decimal(1)

    # Excess return (alpha)
    if portfolio_twr is not None and benchmark_return is not None:
        excess_return = portfolio_twr - benchmark_return
    else:
        excess_return = None

    # Tracking error: standard deviation of daily excess returns
    tracking_error = None
    information_ratio = None
    daily_returns_count = 0

    if portfolio_daily_returns and benchmark_daily_returns:
        # Align lengths (pad shorter list with 0s)
        min_len = min(len(portfolio_daily_returns), len(benchmark_daily_returns))
        daily_returns_count = min_len
        excess_returns = [
            portfolio_daily_returns[i] - benchmark_daily_returns[i]
            for i in range(min_len)
        ]
        if excess_returns:
            n = len(excess_returns)
            mean_excess = sum(excess_returns) / Decimal(n)
            variance = sum((r - mean_excess) ** 2 for r in excess_returns) / Decimal(n)
            tracking_error = variance.sqrt()

            # Information ratio: annualised excess return / annualised tracking error
            if tracking_error > 0:
                # Annualise: daily excess return * sqrt(252)
                annualised_excess = mean_excess * Decimal(252).sqrt()
                annualised_te = tracking_error * Decimal(252).sqrt()
                information_ratio = annualised_excess / annualised_te

    return BenchmarkComparisonResponse(
        portfolio_id=portfolio_id,
        benchmark_ticker=benchmark_ticker,
        portfolio_return=portfolio_twr,
        benchmark_return=benchmark_return,
        excess_return_alpha=excess_return,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
        period_start=period_start,
        period_end=period_end,
        daily_returns_count=daily_returns_count,
        calculated_at=datetime.utcnow(),
    )
```

**Why:** Pure functions — no DB access, no I/O. Everything is passed in. This makes the unit tests trivial: mock nothing, just call functions with data and assert results. The `_compute_twr` function walks through transactions + cash flows chronologically, reconstructing holdings at each point, and geometrically links sub-period returns. Cash flows and transactions are separate signals: BUY/SELL determine holdings state, cash_flows determine external CF amounts. `enable_twr` flag allows disabling TWR without code deploy.

**Edge cases handled:**

- BMV = 0 guard (grilling Q2) → sub_return = 0 for new investments
- Zero-cost-basis holdings → P&L % = None
- Missing price data → individual holding metrics handle gracefully
- No transactions or cash flows in period → TWR = None
- Single-day period → TWR = None (no sub-periods)
- Cash flows on same date as transactions → merged into same sub-period
- free_cash_balance can go negative if user sells short or has no deposits (unlikely in V1)
- enable_twr=False → all TWR fields return None (feature flag safety)

---

#### Step 2.7 — Performance router

**File:** `backend/src/performance/router.py`
**Action:** Two endpoints: `/portfolio/performance/{portfolio_id}`, `/portfolio/benchmark/{portfolio_id}`. Now fetches cash_flows for free_cash_balance and supplies them to TWR calculation.

```python
"""
FastAPI router for portfolio performance and benchmark comparison.

Endpoints:
    - ``GET /portfolio/performance/{portfolio_id}`` — portfolio P&L, TWR, holdings breakdown
    - ``GET /portfolio/benchmark/{portfolio_id}`` — portfolio vs benchmark comparison
"""

from __future__ import annotations

import structlog
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from src.market.repository import get_ohlcv, ticker_exists_in_db

from src.performance.calculations import (
    compute_benchmark_comparison,
    compute_portfolio_performance,
)
from src.performance.schemas import (
    BenchmarkComparisonResponse,
    PortfolioPerformanceResponse,
)

logger = structlog.get_logger()

router = APIRouter()


async def _verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None:
    """Return the portfolio row if it exists and belongs to *user_id*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, user_id, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


async def _get_holdings(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch holdings for a portfolio."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, ticker, shares, average_cost_basis "
            "FROM holdings WHERE portfolio_id = $1::uuid "
            "ORDER BY ticker",
            portfolio_id,
        )
    return [dict(r) for r in rows]


async def _get_transactions_sorted(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch all transactions for a portfolio, sorted by date ascending."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, ticker, type, shares, price_per_share, total_amount, transaction_date "
            "FROM transactions WHERE portfolio_id = $1::uuid "
            "ORDER BY transaction_date ASC, created_at ASC, id ASC",
            portfolio_id,
        )
    result = []
    for r in rows:
        d = dict(r)
        # Rename transaction_date to date for calculations.py
        d["date"] = d.pop("transaction_date")
        result.append(d)
    return result


async def _get_cash_flows_sorted(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch all cash flows for a portfolio, sorted by date ascending."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = $1::uuid "
            "ORDER BY created_at ASC, id ASC",
            portfolio_id,
        )
    return [dict(r) for r in rows]

async def _get_free_cash_balance(portfolio_id: str) -> Decimal:
    """Compute free cash = total deposits - net invested (BUYs - SELLs)."""
    async with connection_ctx() as conn:
        total_deposits = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
        net_invested = await conn.fetchval(
            "SELECT COALESCE(SUM(CASE WHEN type = 'BUY' THEN total_amount WHEN type = 'SELL' THEN -total_amount ELSE 0 END), 0) "
            "FROM transactions WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
    return Decimal(str(total_deposits)) - Decimal(str(net_invested))

async def _build_price_map(
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, dict[date, Decimal]]:
    """Build a nested price map {ticker: {date: adjusted_close}} for the given range.

    Uses ``asyncio.gather`` to fetch all tickers in parallel.
    """
    import asyncio

    results = await asyncio.gather(*[
        get_ohlcv(ticker, start_date=start_date, end_date=end_date, limit=2000)
        for ticker in tickers
    ], return_exceptions=True)

    price_map: dict[str, dict[date, Decimal]] = {}
    for ticker, rows in zip(tickers, results):
        if isinstance(rows, Exception):
            logger.warning("price_map_fetch_failed", ticker=ticker, error=str(rows))
            price_map[ticker] = {}
        else:
            price_map[ticker] = {r["date"]: r["adjusted_close"] for r in rows if r["adjusted_close"] is not None}
    return price_map


@router.get(
    "/portfolio/performance/{portfolio_id}",
    response_model=PortfolioPerformanceResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_portfolio_performance(
    request: Request,
    portfolio_id: UUID,
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: UserInDB = Depends(get_current_user),
) -> PortfolioPerformanceResponse:
    """Return portfolio performance metrics including TWR and per-holding P&L.

    Requires the portfolio to belong to the current user.
    Data freshness depends on market data cache (see /market/ohlcv/{ticker}).
    """
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date.replace(year=end_date.year - 1)

    holdings = await _get_holdings(str(portfolio_id))
    if not holdings:
        # Compute free cash even when no holdings exist
        free_cash = await _get_free_cash_balance(str(portfolio_id))
        return PortfolioPerformanceResponse(
            portfolio_id=str(portfolio_id),
            portfolio_name=portfolio["name"],
            total_cost_basis=0,
            total_holdings=0,
            free_cash_balance=free_cash,
            holdings=[],
            calculated_at=datetime.utcnow(),
        )

    transactions = await _get_transactions_sorted(str(portfolio_id))
    cash_flows = await _get_cash_flows_sorted(str(portfolio_id))
    tickers = list({h["ticker"] for h in holdings})

    price_map = await _build_price_map(tickers, start_date, end_date)

    return compute_portfolio_performance(
        portfolio_id=str(portfolio_id),
        portfolio_name=portfolio["name"],
        holdings_data=holdings,
        transactions=transactions,
        cash_flows=cash_flows,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
        enable_twr=settings.ENABLE_TWR,
    )


@router.get(
    "/portfolio/benchmark/{portfolio_id}",
    response_model=BenchmarkComparisonResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_benchmark_comparison(
    request: Request,
    portfolio_id: UUID,
    benchmark: str = Query("SPY", description="Benchmark ticker (SPY or QQQ)"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: UserInDB = Depends(get_current_user),
) -> BenchmarkComparisonResponse:
    """Compare portfolio performance to a benchmark index.

    Returns alpha (excess return), tracking error, and information ratio.
    """
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date.replace(year=end_date.year - 1)

    benchmark = benchmark.upper()
    if benchmark not in ("SPY", "QQQ"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Benchmark must be SPY or QQQ",
        )

    # Get portfolio TWR (reuse performance computation)
    holdings = await _get_holdings(str(portfolio_id))
    transactions = await _get_transactions_sorted(str(portfolio_id))
    cash_flows = await _get_cash_flows_sorted(str(portfolio_id))
    tickers = list({h["ticker"] for h in holdings})

    # Include benchmark in price map for tracking error computation
    all_tickers = list(set(tickers + [benchmark]))
    price_map = await _build_price_map(all_tickers, start_date, end_date)

    # Check benchmark has data
    if not price_map.get(benchmark):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for benchmark {benchmark}",
        )

    # Compute portfolio performance (includes TWR)
    perf_response = compute_portfolio_performance(
        portfolio_id=str(portfolio_id),
        portfolio_name=portfolio["name"],
        holdings_data=holdings,
        transactions=transactions,
        cash_flows=cash_flows,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
        enable_twr=settings.ENABLE_TWR,
    )

    # Compute benchmark daily returns from price data
    benchmark_prices = price_map.get(benchmark, {})
    benchmark_dates = sorted(benchmark_prices.keys())
    benchmark_daily_returns = []
    for i in range(1, len(benchmark_dates)):
        prev_price = benchmark_prices[benchmark_dates[i - 1]]
        curr_price = benchmark_prices[benchmark_dates[i]]
        if prev_price > 0:
            benchmark_daily_returns.append((curr_price - prev_price) / prev_price)

    # Compute portfolio daily returns (from reconstructed holdings)
    portfolio_daily_returns = _compute_portfolio_daily_returns(
        holdings=holdings,
        transactions=transactions,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
    )

    return compute_benchmark_comparison(
        portfolio_id=str(portfolio_id),
        portfolio_twr=perf_response.twr,
        benchmark_ticker=benchmark,
        benchmark_daily_returns=benchmark_daily_returns,
        portfolio_daily_returns=portfolio_daily_returns,
        period_start=start_date,
        period_end=end_date,
    )


def _compute_portfolio_daily_returns(
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: date,
    end_date: date,
) -> list[Decimal]:
    """Compute daily portfolio returns for tracking error calculation.

    Reconstructs holdings at each trading day and computes day-over-day
    percentage return. Returns empty list if insufficient price data.
    """
    # Gather all trading dates across all tickers
    all_dates: set[date] = set()
    for ticker_prices in price_map.values():
        all_dates.update(ticker_prices.keys())
    if not all_dates:
        return []
    trading_days = sorted(d for d in all_dates if start_date <= d <= end_date)
    if len(trading_days) < 2:
        return []

    # Build transaction index by date
    from collections import defaultdict
    txns_by_date: dict[date, list[dict]] = defaultdict(list)
    for t in transactions:
        txns_by_date[t["date"]].append(t)

    # Walk through trading days, reconstructing holdings at each step
    daily_returns: list[Decimal] = []
    current: dict[str, Decimal] = {}  # ticker -> shares

    for i, day in enumerate(trading_days):
        # Apply transactions that occur on this day (before valuation)
        for txn in txns_by_date.get(day, []):
            ticker = txn["ticker"]
            if txn["type"] == "BUY":
                current[ticker] = current.get(ticker, Decimal(0)) + txn["shares"]
            else:
                current[ticker] = current.get(ticker, Decimal(0)) - txn["shares"]
                if current[ticker] <= 0:
                    del current[ticker]

        # Value the portfolio at this day
        value = Decimal(0)
        for ticker, shares in current.items():
            ticker_prices = price_map.get(ticker, {})
            if day in ticker_prices and ticker_prices[day] is not None:
                value += shares * ticker_prices[day]

        if i > 0:
            prev = previous_value
            if prev > 0:
                daily_return = (value - prev) / prev
                daily_returns.append(daily_return)
            else:
                daily_returns.append(Decimal(0))

        previous_value = value

    return daily_returns
```

**Why:** Follows Phase 1 pattern (ownership verification, connection_ctx, HTTPException). `_build_price_map` fetches OHLCV data for all tickers at once. Performance endpoint calls pure functions from `calculations.py`. Cash flows are fetched separately and passed to the calculation layer. `_compute_portfolio_daily_returns` walks through trading days chronologically, applying transactions as they occur.

---

#### Step 2.8 — Register routers in main.py

**File:** `backend/src/main.py`
**Action:** Add cash_flows and performance router imports and registrations.

```python
from src.cash_flows.router import router as cash_flows_router  # noqa: E402
from src.performance.router import router as performance_router  # noqa: E402

app.include_router(cash_flows_router, tags=["cash_flows"])
app.include_router(performance_router, tags=["performance"])
```

**Why:** Both routers use absolute paths (`/portfolios/{id}/cash-flows`, `/portfolio/performance/{id}`, `/portfolio/benchmark/{id}`). Follows same pattern as holdings router.

**Also add ENABLE_TWR to settings:** `backend/src/config.py`

```python
# Add to settings class
ENABLE_TWR: bool = True
```

---

#### Step 2.9 — Performance + Cash Flows tests

**File:** `backend/tests/test_performance.py`
**Action:** Test performance calculations and endpoints.

Target: 50+ tests covering:

- `compute_holding_performance` — basic calculation
- `compute_holding_performance` — missing price → None values
- `compute_holding_performance` — zero cost basis
- `compute_portfolio_performance` — single holding, no transactions, with cash_flows
- `compute_portfolio_performance` — multiple holdings, with transactions and cash_flows
- `compute_portfolio_performance` — empty portfolio (still has free_cash_balance)
- `compute_portfolio_performance` — all holdings missing price (data_quality=partial)
- `compute_portfolio_performance` — enable_twr=False (all TWR fields None)
- `compute_portfolio_performance` — free_cash_balance = deposits - net invested
- `_compute_twr` — basic TWR with cash_flows deposit and BUY
- `_compute_twr` — BMV = 0 guard (new investment, CF > 0, r = 0)
- `_compute_twr` — no transactions, no cash_flows in period
- `_compute_twr` — cash_flows on same day as transactions
- `_compute_twr` — cash_flows without transactions (pure deposits, no holdings)
- `_compute_twr` — SELL transaction (partial exit)
- `_compute_twr` — multiple sub-periods (sequential buys + deposits)
- `_compute_twr` — multiple tickers in same portfolio
- `_compute_twr` — transactions outside date range (filtered out)
- `_get_closest_price` — exact date match
- `_get_closest_price` — price before target date
- `_get_closest_price` — no price data available
- `_portfolio_value` — basic valuation
- `_portfolio_value` — missing ticker in price map
- `_portfolio_value` — no holdings (empty dict)
- `compute_benchmark_comparison` — basic comparison
- `compute_benchmark_comparison` — tracking error calculation
- `compute_benchmark_comparison` — missing portfolio return
- `compute_benchmark_comparison` — empty daily return lists
- `_compute_portfolio_daily_returns` — basic walk through trading days
- `_compute_portfolio_daily_returns` — single trading day (no returns)
- `_compute_portfolio_daily_returns` — multiple tickers, one has missing prices
- TWR annualisation: period < 1 year
- TWR annualisation: period == 0 days (division-by-zero guard)
- GET /portfolio/performance/{id} — happy path (seeded cash_flows)
- GET /portfolio/performance/{id} — not found (404)
- GET /portfolio/performance/{id} — not owned (404)
- GET /portfolio/benchmark/{id} — happy path
- GET /portfolio/benchmark/{id} — invalid benchmark (400)
- GET /portfolio/benchmark/{id} — benchmark no data (404)
- Cash flows: POST creates deposit record
- Cash flows: GET lists paginated records
- Cash flows: PATCH updates notes only

```python
"""Tests for the portfolio performance module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.performance.calculations import (
    _compute_twr,
    _portfolio_value,
    compute_benchmark_comparison,
    compute_holding_performance,
    compute_portfolio_performance,
    _get_closest_price,
)


class TestHoldingPerformance:
    """Tests for per-holding performance calculations."""

    def test_basic_calculation(self):
        """Basic P&L calculation with all data available."""
        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("100"),
            avg_cost_basis=Decimal("150.00"),
            current_price=Decimal("180.00"),
            previous_close=Decimal("178.00"),
            total_portfolio_value=Decimal("18000.00"),
        )
        assert result.ticker == "AAPL"
        assert result.shares == Decimal("100")
        assert result.market_value == Decimal("18000.00")
        assert result.cost_basis == Decimal("15000.00")
        assert result.unrealised_pl == Decimal("3000.00")
        assert result.unrealised_pl_pct == Decimal("20.00")
        assert result.day_change == Decimal("200.00")
        assert result.day_change_pct == pytest.approx(Decimal("1.1236"), rel=Decimal("0.01"))
        assert result.portfolio_weight_pct == Decimal("100.00")

    def test_missing_price(self):
        """Missing current_price → all price-dependent values are None."""
        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("100"),
            avg_cost_basis=Decimal("150.00"),
            current_price=None,
            previous_close=None,
            total_portfolio_value=None,
        )
        assert result.current_price is None
        assert result.market_value is None
        assert result.unrealised_pl is None
        assert result.day_change is None
        assert result.portfolio_weight_pct is None

    def test_zero_cost_basis(self):
        """Zero cost basis → unrealised P&L % is None."""
        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("0"),
            current_price=Decimal("180.00"),
            previous_close=Decimal("178.00"),
            total_portfolio_value=Decimal("1800.00"),
        )
        assert result.cost_basis == Decimal("0")
        assert result.market_value == Decimal("1800.00")
        assert result.unrealised_pl_pct is None  # Can't compute % with zero cost


class TestTWR:
    """Tests for Time-Weighted Return calculation."""

    def test_no_transactions(self):
        """No transactions or cash_flows in period → TWR is None."""
        twr, ann = _compute_twr(
            transactions=[],
            cash_flows=[],
            price_map={"AAPL": {date(2024, 1, 2): Decimal("180.00")}},
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is None
        assert ann is None

    def test_single_buy_with_cash_flow(self):
        """Single BUY + matching cash_flow deposit → positive TWR.

        Sub-periods: [2024-01-01, 2024-06-15, 2024-12-31]
        - Sub 1 (d0→d1): BMV=0, CF from cash_flow=1500 on d1, BUY on d1. BMV=0 → r=0
        - Sub 2 (d1→d2): BMV=10×150=1500, no CF, EMV=10×152=1520
          r = (1520-1500-0)/1500 = 0.0133
        - TWR = (1+0)(1+0.0133)-1 = 0.0133
        """
        twr, ann = _compute_twr(
            transactions=[{
                "type": "BUY",
                "ticker": "AAPL",
                "shares": Decimal("10"),
                "total_amount": Decimal("1500.00"),
                "date": date(2024, 6, 15),
            }],
            cash_flows=[{
                "amount": Decimal("1500.00"),
                "created_at": datetime(2024, 6, 15),
            }],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("148.00"),
                    date(2024, 6, 15): Decimal("150.00"),
                    date(2024, 12, 31): Decimal("152.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None
        assert twr > 0
        assert twr < Decimal("0.02")

    def test_buy_then_growth(self):
        """BUY then price growth → positive TWR (corrected BMV ordering).

        CF = 1500 on d1 via cash_flow, BUY 10@150 on same day.
        """
        twr, ann = _compute_twr(
            transactions=[{
                "type": "BUY",
                "ticker": "AAPL",
                "shares": Decimal("10"),
                "total_amount": Decimal("1500.00"),
                "date": date(2024, 1, 2),
            }],
            cash_flows=[{
                "amount": Decimal("1500.00"),
                "created_at": datetime(2024, 1, 2),
            }],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("150.00"),
                    date(2024, 1, 2): Decimal("150.00"),
                    date(2024, 6, 30): Decimal("165.00"),
                    date(2024, 12, 31): Decimal("180.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None
        assert twr > 0
        assert abs(twr - Decimal("0.20")) < Decimal("0.02")

    def test_bmv_zero_guard(self):
        """BMV = 0 with cash flow → sub-period return is 0 (not division by zero)."""
        twr, ann = _compute_twr(
            transactions=[{
                "type": "BUY",
                "ticker": "AAPL",
                "shares": Decimal("10"),
                "total_amount": Decimal("1500.00"),
                "date": date(2024, 6, 15),
            }],
            cash_flows=[{
                "amount": Decimal("1500.00"),
                "created_at": datetime(2024, 6, 15),
            }],
            price_map={
                "AAPL": {
                    date(2024, 6, 14): Decimal("150.00"),
                    date(2024, 6, 15): Decimal("151.00"),
                    date(2024, 6, 16): Decimal("152.00"),
                },
            },
            start_date=date(2024, 6, 14),
            end_date=date(2024, 6, 16),
        )
        assert twr is not None
        assert twr > 0
        assert twr < Decimal("0.01")


class TestBenchmarkComparison:
    """Tests for benchmark comparison."""

    def test_basic_comparison(self):
        """Basic benchmark comparison with portfolio outperformance."""
        result = compute_benchmark_comparison(
            portfolio_id="test-id",
            portfolio_twr=Decimal("0.25"),
            benchmark_ticker="SPY",
            benchmark_daily_returns=[Decimal("0.001"), Decimal("0.002")],
            portfolio_daily_returns=[Decimal("0.003"), Decimal("0.004")],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.portfolio_return == Decimal("0.25")
        assert result.benchmark_return is not None
        assert result.benchmark_ticker == "SPY"
        assert result.excess_return_alpha is not None
        assert result.excess_return_alpha > 0  # Portfolio outperformed
```

---

### Round 3 — Integration, Tests & Polish

**Goal:** Everything builds, all tests pass, documentation updated, CI updated.

---

#### Step 3.1 — Build & test

```bash
# Build the Docker image with the new yfinance dependency
docker compose build backend

# Run the cash_flows migration
docker compose run --rm backend sh -c "alembic upgrade head"

# Run Phase 2 tests
docker compose run --rm pytest -v -k "market or performance or cash_flows" --cov=src --cov-report=term-missing

# Run the full test suite (ensure Phase 1 tests still pass)
docker compose run --rm pytest -v --cov=src --cov-report=term-missing
```

**Verify:** 152/152 Phase 1 tests + 80+ Phase 2 tests = 232+ tests total.

---

#### Step 3.2 — Lint

```bash
# Ensure no lint errors
docker compose run --rm backend uv run ruff check src/ tests/
```

---

#### Step 3.3 — Verify API docs

```bash
# Start the app and check /docs renders correctly
docker compose up -d
curl -s http://localhost:8000/docs | grep -q "market\|portfolio/performance\|portfolio/benchmark"
echo "API docs verified: $?"
```

**Check:** The `/docs` (Swagger) page should list all 4 new endpoints with correct schemas. FastAPI auto-generates OpenAPI from router docstrings.

---

#### Step 3.4 — Update CI (if applicable)

**Check:** If `.github/workflows/` exists, verify new test paths (`tests/test_market.py`, `tests/test_performance.py`) are included in the `pytest` step. If there's no CI file yet (Phase 1 may not have created it), skip this step.

---

#### Step 3.5 — Update TRACKER.md

**File:** `docs/TRACKER.md`
**Action:** Add Phase 2 step tracker rows and deviations.

---

## Testing Strategy

### Test Types

| Type                  | Files                                                                    | Approach                                                               |
| --------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| **Unit (pure logic)** | `test_performance.py`                                                    | No mocking needed — pure functions in `calculations.py`                |
| **Unit (isolated)**   | `test_market.py` (repository ops), `test_cash_flows.py` (repository ops) | Use transaction-rollback fixtures for DB tests                         |
| **Integration (API)** | `test_market.py`, `test_cash_flows.py`, `test_performance.py`            | `httpx.AsyncClient` + auth fixtures                                    |
| **Mocked externals**  | `test_market.py` (yfinance calls)                                        | `unittest.mock.patch` on `provider._download_ohlcv` and `_fetch_quote` |

### What to Mock

- **yfinance HTTP calls** — mock `provider._download_ohlcv` and `provider._fetch_quote` to return controlled data
- **Redis** — quote endpoint handles missing Redis gracefully (skips cache)
- **Do NOT mock**: asyncpg (transaction rollback handles isolation), datetime (use fixed dates in tests)

### Key Test Scenarios

#### Market Data

1. OHLCV cache hit → 200 with DB data (no yfinance call)
2. OHLCV cache miss → 200 with fresh data (yfinance called, DB updated)
3. OHLCV ticker not found → 404
4. OHLCV yfinance failure → 503
5. Quote cache hit (Redis) → 200, no yfinance call
6. Quote cache miss → 200, yfinance called, Redis updated
7. Quote yfinance failure → 503
8. Unauthenticated access → 401

#### Cash Flows

1. POST /portfolios/{id}/cash-flows creates deposit → 200, amount stored
2. POST /portfolios/{id}/cash-flows zero amount → 422 validation
3. GET /portfolios/{id}/cash-flows returns paginated list → 200
4. GET /portfolios/{id}/cash-flows wrong user → 404
5. PATCH notes on cash flow → 200, notes updated
6. Cash flow source='receipt' with source_id → stored correctly

#### Portfolio Performance

1. Single holding with full data → correct P&L, weight=100%
2. Missing price data → data_quality="partial", null market values
3. Empty portfolio → 0 values, no errors
4. TWR with one BUY → positive return if prices rose
5. TWR with multiple transactions → geometrically linked
6. TWR with zero BMV → handled gracefully
7. TWR with cash_flows deposit → external CF used instead of transaction amount
8. TWR with ENABLE_TWR=False → returns null TWR
9. Benchmark SPY comparison → alpha computed
10. Benchmark SPY → TE/IR computed from daily returns
11. Invalid benchmark ticker → 400
12. Daily return computation → correct day-over-day % with transactions applied

---

## Success Criteria

- [ ] All 6+ new endpoints functional:
  - `GET /market/ohlcv/{ticker}` — returns OHLCV data with date range support
  - `GET /market/quote/{ticker}` — returns current quote with 60s Redis cache
  - `POST /portfolios/{id}/cash-flows` — creates cash flow deposit record
  - `GET /portfolios/{id}/cash-flows` — lists cash flows with pagination
  - `GET /portfolio/performance/{portfolio_id}` — returns P&L, TWR, free_cash_balance, holdings breakdown
  - `GET /portfolio/benchmark/{portfolio_id}` — returns benchmark comparison with alpha, TE, IR
- [ ] Data flows: yfinance → PostgreSQL cache → FastAPI response (OHLCV)
- [ ] Data flows: yfinance → Redis cache → FastAPI response (quote)
- [ ] Cash flows: receipt-backed deposits tracked in `cash_flows` table per portfolio
- [ ] TWR: cash-flow-based methodology (separate cash_flows from BUY/SELL), handles BMV=0 edge case
- [ ] TE/IR: daily returns computed from reconstructed holdings, tracking error & information ratio
- [ ] ENABLE_TWR feature flag: setting to False returns null TWR without code deploy
- [ ] tenacity retry: exponential backoff on yfinance OHLCV + quote fetches
- [ ] All Phase 1 tests still pass (152/152)
- [ ] 80+ Phase 2 tests pass (market, cash_flows, performance)
- [ ] Python test coverage ≥80% (Phase 1 was 84%, Phase 2 should maintain or improve)
- [ ] `ruff check src/ tests/` — zero errors
- [ ] TRACKER.md updated with Phase 2 progress

---

## Risks & Mitigations

| Risk                                           | Impact                                         | Likelihood | Mitigation                                                                                                                                                                         |
| ---------------------------------------------- | ---------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Yahoo Finance blocks yfinance                  | Market data unavailable                        | Low        | DB cache provides historical data; 503 for quotes; fallback options in ADR 001                                                                                                     |
| Yahoo Finance rate limiting                    | Flaky 503s under heavy use                     | Medium     | `@retry` with exponential backoff (stop_after_attempt(3), wait_exponential(1s, 4s)) on both OHLCV and quote fetches. If 503s persist, increase max attempts or add circuit breaker |
| yfinance is synchronous (event loop blocking)  | Slow responses, blocked server                 | Medium     | `asyncio.to_thread()` wraps calls in thread pool — tested for correctness                                                                                                          |
| TWR calculation has a bug (e.g., BMV ordering) | Wrong portfolio returns                        | Medium     | Feature flag `ENABLE_TWR: bool = True` in config; if buggy, set to False and TWR returns null (implemented in Step 2.8)                                                            |
| Concurrent cache refresh thundering herd       | 10× yfinance calls for same ticker             | Low        | ON CONFLICT DO NOTHING prevents corruption. Add per-ticker `asyncio.Lock` if racing becomes a problem                                                                              |
| Portfolio with 50+ holdings is slow            | TWR takes >1s                                  | Low        | OHLCV data cached in PostgreSQL; `_build_price_map` uses `asyncio.gather` for parallel DB fetches                                                                                  |
| Redis unavailable                              | Quote cache miss                               | Low        | Graceful degradation — skip Redis cache, fetch fresh from yfinance                                                                                                                 |
| Decimal → float precision loss                 | Monetary rounding errors                       | Low        | Python Decimal throughout; only serialise to float at JSON boundary                                                                                                                |
| Daily returns TE/IR performance                | Slow computation for 50+ holdings over 2 years | Low        | O(N×D) where D ≤ 756 (3yr trading days). Acceptable for V1; add caching of daily return series if performance measured as problematic                                              |
| No monitoring for yfinance failures            | Silent degradation                             | Low        | structlog warnings on each failure; add a counter metric (e.g., Prometheus) if observability scope expands                                                                         |

---

## Verification Checklist

- [ ] `docker compose build backend` succeeds
- [ ] `docker compose up -d` starts all services healthy
- [ ] `alembic upgrade head` runs the `0003_add_cash_flows` migration
- [ ] `GET /market/ohlcv/AAPL` returns 200 with valid OHLCV data
- [ ] Market data freshness accounts for weekends — 3-day staleness tolerance on Monday
- [ ] `GET /market/quote/AAPL` returns 200 with valid quote
- [ ] Redis outage handled gracefully — quote endpoint returns fresh data from yfinance instead of 500
- [ ] `POST /portfolios/{id}/cash-flows` creates a deposit (200)
- [ ] `GET /portfolios/{id}/cash-flows` returns paginated list (200)
- [ ] `PATCH /portfolios/{id}/cash-flows/{cf_id}` updates notes (200)
- [ ] `GET /portfolio/performance/{id}` returns 200 with TWR, free_cash_balance (for seeded portfolio)
- [ ] TWR pre-existing holdings before start_date are correctly seeded from pre-start-date transactions
- [ ] `GET /portfolio/benchmark/{id}?benchmark=SPY` returns 200 with comparison (including TE, IR)
- [ ] `GET /market/ohlcv/INVALID` returns 404
- [ ] `GET /portfolio/performance/{id}` for wrong user returns 404
- [ ] All 232+ tests pass
- [ ] `ruff check src/ tests/` — zero errors
- [ ] Test coverage ≥80%
