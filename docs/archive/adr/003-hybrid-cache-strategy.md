# ADR 003: Hybrid Cache Strategy — PostgreSQL for OHLCV, Redis for Quotes

**Date:** 2026-06-30
**Status:** Accepted
**Phase:** 2 — Market Data Layer

## Context

Market data endpoints need a caching strategy to:

1. Avoid redundant yfinance calls (rate limits, latency)
2. Serve historical data quickly (DB is faster than HTTP)
3. Provide current quotes without stale data
4. Work within the existing infrastructure (PostgreSQL + Redis running in Docker Compose)

The `ohlcv_prices` table already exists in the schema (from Phase 1's initial migration). Redis is already wired for JWT blacklisting and rate limiting.

## Decision

Use a **split cache strategy**:

| Data Type                           | Cache                        | Retention  | Refresh Trigger                 |
| ----------------------------------- | ---------------------------- | ---------- | ------------------------------- |
| Historical OHLCV (≥1 year ago)      | PostgreSQL (`ohlcv_prices`)  | Forever    | On first request for the ticker |
| Recent OHLCV (<1 year, incl. today) | PostgreSQL (`ohlcv_prices`)  | Daily      | If `max(date)` < yesterday      |
| Current Quote                       | Redis (hash keyed by ticker) | 60 seconds | If not in Redis or TTL expired  |

### Refresh Logic (Pseudocode)

```
GET /market/ohlcv/{ticker}
  → Query ohlcv_prices WHERE ticker = $1 ORDER BY date DESC LIMIT 1
  → If newest row is yesterday or newer → return cached data (it's fresh)
  → Else → run yfinance download → INSERT new rows → return merged data

GET /market/quote/{ticker}
  → Try Redis GET quote:{ticker}
  → If found and age < 60s → return cached quote
  → Else → run yfinance ticker.info → cache in Redis → return fresh quote
```

## Rationale

- Historical OHLCV is immutable once the market closes — caching it forever in PostgreSQL is correct.
- Today's OHLCV data is not available until market close (or next day) for most tickers, so refreshing daily is sufficient.
- Current quotes change throughout the trading day — 60-second Redis cache prevents yfinance hammering on screen refreshes while being fresh enough for portfolio tracking use cases.
- Redis is already running (Phase 1 requirement for rate limiting). No new infrastructure.

## Consequences

- `ohlcv_prices` grows unboundedly as new daily rows are inserted. No eviction policy needed — price data is the product.
- Quote endpoint will have at most 60 seconds of staleness during market hours. Acceptable for portfolio tracking (not algorithmic trading).
- First request for a newly-added ticker will be slow (~200-500ms for yfinance HTTP call). Subsequent requests hit the DB cache.
- Write operations to the PG cache can be batched (INSERT ... ON CONFLICT DO NOTHING for idempotent loads).

## Alternatives Considered

| Alternative                                        | Reason Rejected                                                                     |
| -------------------------------------------------- | ----------------------------------------------------------------------------------- |
| PostgreSQL-only (cache everything in ohlcv_prices) | Quote refresh every request means no short-term caching — unnecessary yfinance load |
| Redis-only (cache OHLCV in Redis as well)          | Redis memory is expensive for time-series data; PostgreSQL handles it natively      |
| yfinance-only (no cache)                           | Unacceptable latency and rate limit risk for a portfolio tracking app               |
