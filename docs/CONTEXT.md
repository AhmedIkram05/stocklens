# Phase 2 — Domain Glossary

> **Purpose:** Shared vocabulary for market data and portfolio analytics.
> **Audience:** AI coding agents implementing Phase 2.
> **All terms defined here are normative** — if implementation docs use different language, this glossary wins.

---

## Market Data

| Term               | Definition                                                                                                        | Attributes / Constraints                                                                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ticker**         | Exchange-traded symbol (e.g. `AAPL`, `SPY`, `QQQ`).                                                               | Upper case, 1–10 chars. Identical to the `ticker` column in `holdings`, `transactions`, `ohlcv_prices`.                                                    |
| **OHLCV**          | Open / High / Low / Close / Volume — the standard daily price record.                                             | `open, high, low, close, adjusted_close`: DECIMAL(12,4). `volume`: BIGINT.                                                                                 |
| **Adjusted Close** | Closing price adjusted for splits and dividends. Used for return calculations so historical returns are accurate. | Stored in `ohlcv_prices.adjusted_close`. Used by all return computations.                                                                                  |
| **Quote**          | A real-time (or near-real-time) price snapshot for a ticker.                                                      | Contains: `ticker`, `price`, `change`, `change_pct`, `previous_close`, `volume`, `timestamp`.                                                              |
| **Data Freshness** | Age of cached market data. Determines whether a cache-hit is returned or a fetch from yfinance is triggered.      | **Historical** (≥1 year ago): cache forever. **Recent** (<1 year): refresh daily after market close. **Quote**: refresh every request (1-min Redis cache). |
| **yfinance**       | The Python library (`yfinance`, unoffical) used to fetch Yahoo Finance data.                                      | Synchronous library wrapped with `asyncio.to_thread()` for non-blocking usage.                                                                             |

### Data Flow

```
Client → FastAPI → market router → yfinance provider → ohlcv_prices (DB cache) → response
                                      │
                                      └──→ If cache is fresh, skip yfinance
```

---

## Portfolio Performance

| Term                      | Definition                                                                                                                                                                              | Formula                                                                                      |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Market Value**          | Current worth of a holding.                                                                                                                                                             | `shares × current_price`                                                                     |
| **Total Portfolio Value** | Sum of market values across all holdings.                                                                                                                                               | `Σ(shares_i × current_price_i)`                                                              |
| **Cost Basis**            | Total amount invested in a holding.                                                                                                                                                     | `shares × average_cost_basis`                                                                |
| **Total Cost Basis**      | Sum of cost bases across all holdings.                                                                                                                                                  | `Σ(shares_i × avg_cost_basis_i)`                                                             |
| **Unrealised P&L**        | Profit/loss on paper (unrealised).                                                                                                                                                      | `market_value − cost_basis`                                                                  |
| **Unrealised P&L %**      | Percentage return on paper.                                                                                                                                                             | `(current_price − avg_cost_basis) / avg_cost_basis × 100`                                    |
| **Day Change**            | Dollar change from previous close.                                                                                                                                                      | `shares × (current_price − previous_close)`                                                  |
| **Day Change %**          | Percentage change from previous close.                                                                                                                                                  | `(current_price − previous_close) / previous_close × 100`                                    |
| **Portfolio Weight**      | Fraction of portfolio in a single holding.                                                                                                                                              | `market_value / total_portfolio_value × 100`                                                 |
| **Net Cash Flow**         | External cash movement for TWR calculation.                                                                                                                                             | Positive = deposit (from cash_flows table). Negative = not supported in V1 (no withdrawals). |
| **Sub-Period Return**     | Return over a period between two cash flows.                                                                                                                                            | `(EMV − BMV − CF) / BMV`                                                                     |
| **TWR**                   | Time-Weighted Return — geometric link of sub-period returns. Industry standard, neutralises cash flow timing. Uses explicit cash_flows records (not inferred from transaction amounts). | `Π(1 + r_i) − 1`                                                                             |
| **Annualised TWR**        | TWR scaled to a 1-year equivalent.                                                                                                                                                      | `(1 + TWR)^(365/days) − 1`                                                                   |
| **Cash Flow (Record)**    | An explicit deposit into a portfolio. Source can be 'receipt' (scan receipt → deposit amount) or 'manual'.                                                                              | Stored in `cash_flows` table. Amount > 0 always (deposits only).                             |
| **Free Cash Balance**     | Uninvested cash in a portfolio.                                                                                                                                                         | `SUM(cash_flows.amount) − SUM(BUY total_amount) + SUM(SELL total_amount)`                    |
| **Receipt Deposit**       | Scanning a physical receipt deposits its `total_amount` as play money. This creates a cash_flow record with source='receipt'. Paper trading: real prices, fake money.                   | Receipt → cash_flow via `source_id` (no FK constraint).                                      |

---

## Benchmark Comparison

| Term                      | Definition                                                                                                                                     | Formula                                                |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| **Benchmark**             | A market index tracked for comparison (SPY, QQQ). Benchmarks have ticker symbols and trade as ETFs, so they have price data in `ohlcv_prices`. | —                                                      |
| **Benchmark Return**      | Total return of a benchmark over the same period.                                                                                              | `(end_price − start_price) / start_price`              |
| **Excess Return (Alpha)** | Portfolio return minus benchmark return.                                                                                                       | `TWR − Benchmark Return`                               |
| **Tracking Error**        | Standard deviation of daily excess returns.                                                                                                    | `σ(portfolio_daily_return − benchmark_daily_return)`   |
| **Information Ratio**     | Risk-adjusted excess return.                                                                                                                   | `Annualised Excess Return / Annualised Tracking Error` |

---

## Caching Strategy

| Cache Layer                     | Scope                       | TTL / Eviction                                                        | Notes                                                              |
| ------------------------------- | --------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **PostgreSQL (`ohlcv_prices`)** | Historical OHLCV per ticker | Cache forever for dates ≥1 year old. Refresh daily for dates <1 year. | Only write, never evict. UNIQUE(ticker, date) prevents duplicates. |
| **Redis**                       | Current quote               | 60 seconds                                                            | Prevents yfinance hammering on refresh-heavy pages.                |
| **In-memory (per request)**     | None                        | N/A                                                                   | Each request fetches fresh, no per-request caching needed.         |

---

## Design Constraints

1. **yfinance is synchronous.** Must be wrapped with `asyncio.to_thread()` or run in a thread pool executor. Cannot use `await yf.download()`.
2. **OHLCV table already exists.** Schema frozen. No migration needed for Phase 2.
3. **No ORM at query time.** All DB access must use asyncpg directly (same pattern as Phase 1).
4. **User-scoped data.** Portfolio performance endpoints must verify ownership (same `user_id` JOIN pattern as Phase 1 holdings).
5. **Decimal precision.** All monetary values use DECIMAL(12,4) in DB, Python `Decimal` in code, serialised as `float` in JSON.
6. **Pydantic for all schemas.** Request/response models use Pydantic v2 with `ConfigDict(json_encoders={Decimal: float})`.

---

## Edge Cases & Risks

| Edge Case                                      | Handling                                                             |
| ---------------------------------------------- | -------------------------------------------------------------------- |
| Missing price data for a holding               | Return `null` for market_value, exclude from TWR, log warning.       |
| Ticker not found in yfinance                   | Return error, do not cache.                                          |
| Empty portfolio (no holdings)                  | Performance endpoint returns 0 value, 0 return, 0 weight.            |
| Portfolio with no transactions (no cash flows) | TWR is calculated as simple return: `(end_value / start_value) − 1`. |
| Single holding, single day                     | Sub-period return formula still works: `(EMV − BMV) / BMV` (CF = 0). |
| Benchmark ticker not found                     | Return error with descriptive message.                               |
| Date range with no price data                  | Return empty series, log warning.                                    |
| yfinance rate limit hit                        | Catch exception, log error, return 503 with retry-after hint.        |
