# Grilling Session — Phase 2 Design Stress-Test

**Date:** 2026-06-30
**Context:** Pre-plan review of all Phase 2 domain concepts, ADRs, and architecture.

---

## Q1: TWR cash flow simplification — what about zero-cost-basis holdings?

**Question:** If a user receives shares via transfer or DRIP (dividend reinvestment), the holding has $0 cost basis. The SELL of those shares generates a cash outflow for TWR — but the original acquisition had no corresponding inflow. Doesn't this inflate returns?

**Answer:** Yes, it would inflate returns in that edge case. For Phase 2, we accept this limitation. Document the TWR methodology as `"transaction-based"` and note that it does not account for non-transaction-based acquisitions (transfers, DRIP, stock splits). A future Phase can add a `cash_flows` table to handle these cases properly.

**Action:** Add `methodology: "transaction-based"` field to the TWR response. Add a docstring caveat.

## Q2: What about the same-day BUY and SELL?

**Question:** A user buys 100 AAPL at $150, sells 50 AAPL at $152 — both on the same day. The sub-period is one day. CF = +$15,000 (buy) − $7,600 (sell) = +$7,400. BMV = 0 (start of day, no holdings). EMV = 50 × $152 = $7,600. r = (7600 − 0 − 7400) / 0 = division by zero!

**Answer:** This is a genuine edge case where the sub-period starts with BMV = 0. The sub-period return is undefined (infinity). Our TWR implementation must handle this:

1. Detect sub-periods where BMV = 0.
2. If BMV = 0 and CF > 0: This is a new investment period. Treat the sub-period return as 0 (the investment hasn't had time to grow yet) and start the return calculation from the next sub-period.
3. If BMV = 0 and CF = 0: Skip this sub-period entirely.

**Action:** TWR implementation must include a guard for BMV = 0 sub-periods.

## Q3: Portfolio with all recent holdings (no price data yet)

**Question:** A user creates a portfolio and adds holdings of `IPO_STOCK` which has no historical data. What happens?

**Answer:** The performance endpoint should gracefully handle missing price data:

- Holdings with no price data → `market_value = null`, `unrealised_pl = null`.
- Total portfolio value → calculated only from holdings that HAVE price data (with a note indicating partial data).
- TWR → if ANY holding has a price gap during the period, TWR is approximate.

**Action:** Performance endpoint must handle null price data gracefully and include a `data_quality` field indicating data completeness.

## Q4: Multiple ticker batch performance

**Question:** A portfolio with 10 holdings triggers 10 separate yfinance calls on the first request. What about 50 holdings?

**Answer:**

- First request: 10 async I/O calls (via `asyncio.gather`) to yfinance through thread pool — ~200-500ms each, but parallelised, so total ~500ms.
- Subsequent requests: DB cache hits — all 10 tickers are already in PostgreSQL, sub-10ms query.

For the yfinance batch, we can use `yf.download(tickers=["AAPL", "MSFT", ...])` which fetches all tickers in a single HTTP call (more efficient than individual calls). But we need to handle the response parsing per-ticker.

**Action:** Use `yf.download(tickers=...)` with a list when fetching multiple tickers. Store results per-ticker in the ohlcv_prices table using individual INSERT statements.

## Q5: yfinance rate limiting / unavailability

**Question:** Yahoo Finance has no official API. What happens when they block yfinance or rate limit it?

**Answer:** Our hybrid cache strategy mitigates this:

- Most requests are cache hits (PostgreSQL for historical, Redis for quotes).
- yfinance is only called when data is missing or stale.
- If yfinance fails:
  1. Cache HIT → return cached data (may be stale, but better than nothing).
  2. Cache MISS → return error 503 with `{"detail": "Market data temporarily unavailable", "retry_after_seconds": 300}`.
- Log the failure for monitoring.

**Action:** yfinance errors must be caught, logged, and translated to appropriate HTTP responses (503 for cache misses, 200 with stale data warning for cache hits with ≥24h old data).

## Q6: TWR over arbitrary date ranges

**Question:** User asks for TWR over the last 5 days, but there are 20+ transactions in that period. Do we create a sub-period for every transaction?

**Answer:** Yes — each unique transaction date defines a sub-period boundary for TWR. This is correct TWR methodology. If there are 20 transaction dates in 5 calendar days, we compute 20 sub-period returns and geometrically link them. This is computationally fine — each sub-period is O(n) where n = number of holdings.

**Action:** TWR implementation must handle any number of sub-periods (no hard cap). For very long periods (10+ years of daily data), we need to ensure the geometric linking loop doesn't accumulate floating-point errors. Use Python `Decimal` throughout.

## Q7: Benchmark comparison methodology

**Question:** How do we compare portfolio TWR to benchmark return? TWR is daily-linked, but benchmark might be a simple start-to-end return.

**Answer:** Both must use the same methodology for fair comparison:

- Portfolio TWR over the requested period → daily linked returns.
- Benchmark return over the same period → calculated from adjusted_close prices (same start/end dates).
- The benchmark return formula: `(end_adjusted_close − start_adjusted_close) / start_adjusted_close`.
- For a more rigorous comparison, compute daily benchmark returns from adjusted_close and link them geometrically (same as TWR methodology).

**Action:** Use the same geometric linking for both portfolio and benchmark returns. Compute daily holding-period returns for both, then link.

## Q8: What about non-trading days?

**Question:** OHLCV data has gaps on weekends and holidays. TWR uses calendar days — what happens when there's no price on a Saturday?

**Answer:**

- The TWR sub-period boundaries are defined by transaction dates and the overall start/end dates, not by daily price points.
- Daily linking: we'd compute a daily return using closing prices on trading days. For non-trading days, there's no price change — the portfolio value doesn't change.
- The simplest approach: only compute sub-period returns on trading days where we have data. Use the closing price from the last trading day for valuation.

**Action:** The implementation should use last_available_close before the sub-period end date if no price data exists on that specific date.

## Q9: Performance endpoint caching

**Question:** Should the performance endpoint be cached? Every request recalculates TWR from scratch.

**Answer:** Performance calculations are fast (<50ms for most portfolios with PostgreSQL caching of market data). The bottlenecks are:

1. Fetching holdings per portfolio (fast — direct asyncpg query)
2. Fetching transactions per portfolio (fast — direct asyncpg query)
3. Fetching OHLCV data per ticker (fast — already in PostgreSQL)
4. The TWR calculation loop (pure Python math, <10ms)

No need for Redis caching on performance endpoints. If it becomes a bottleneck at scale, we can add a result cache with a short TTL (1 hour).

**Action:** No caching for performance endpoints. Keep it simple.

## Q10: yfinance dependency — add to pyproject.toml?

**Question:** Where does yfinance fit in the dependency tree?

**Answer:** Add `yfinance>=0.2.0` to the `[project.dependencies]` list in `pyproject.toml`. This is a production dependency (not dev-only) since it's used at runtime. The Docker image needs to include it.

**Action:** Update pyproject.toml with yfinance.
