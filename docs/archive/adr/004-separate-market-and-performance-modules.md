# ADR 004: Separate `market` and `performance` Modules

**Date:** 2026-06-30
**Status:** Accepted
**Phase:** 2 — Market Data Layer

## Context

Phase 2 introduces two distinct concerns:

1. **Market data** — fetching, caching, and serving raw OHLCV data and quotes (yfinance integration).
2. **Portfolio performance** — computing P&L, TWR, benchmark comparison from holdings + market data.

These could live in a single `analytics` module, but they have different dependencies, changefrequencies, and test profiles.

## Decision

Create two separate top-level modules under `src/`:

```
src/
├── market/          # Market data provider
│   ├── __init__.py
│   ├── provider.py  # yfinance wrapper (async via thread pool)
│   ├── repository.py # ohlcv_prices DB operations
│   ├── schemas.py   # Quote, OHLCVData, MarketDataResponse
│   └── router.py    # /market/ohlcv/{ticker}, /market/quote/{ticker}
│
└── performance/     # Portfolio analytics
    ├── __init__.py
    ├── calculations.py  # TWR, P&L, benchmark logic (pure functions)
    ├── schemas.py       # PerformanceResponse, BenchmarkResponse
    └── router.py        # /portfolio/performance/{id}, /portfolio/benchmark/{id}
```

## Rationale

- **Separation of concerns.** Market data (raw data pipeline) is independent from performance analytics (computation layer). Different change drivers.
- **Testability.** `market/provider.py` has yfinance as an external dependency (requires mocking). `performance/calculations.py` is pure math (no mocking needed). Keeping them separate means tests stay simple.
- **Module cohesion.** The `market` module's `__init__.py` can export its public API (`get_quote`, `get_ohlcv`). The `performance` module computes from raw data it receives via imports.
- **Phase 3 readiness.** The LSTM training in Phase 3 will import from `market/repository.py` to read OHLCV data. A clean interface prevents coupling.
- **Consistency with Phase 1.** Phase 1 has separate modules for `auth`, `portfolios`, `holdings`, `transactions`, `receipts`. Following the same pattern.

## Consequences

- Two new `__init__.py` files, two new routers to register in `main.py`.
- `performance/calculations.py` must import from `market/repository.py` and `src/holdings/` (to get holdings for a portfolio).
- Circular imports are possible (none expected since `market` has no dependency on `performance`).
- Future phases can extend each module independently (e.g., LSTM in Phase 3 imports from `market`, not `performance`).

## Alternatives Considered

| Alternative                                                 | Reason Rejected                                                                                                        |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Single `analytics/` module                                  | Cohesion too low — market data fetching and performance calculation are different concerns with different dependencies |
| Fold into existing `portfolios/` module                     | Would bloat the portfolios module with yfinance and TWR logic — violates Single Responsibility                         |
| `analytics/market/` and `analytics/performance/` submodules | Extra nesting adds no value over top-level modules                                                                     |
