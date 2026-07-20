# ADR 001: Synchronous yfinance wrapped in thread pool

**Date:** 2026-06-30
**Status:** Accepted
**Phase:** 2 — Market Data Layer

## Context

Phase 2 needs a market data provider. The two practical options are:

1. **yfinance** — unofficial Yahoo Finance API, synchronous, widely used, no API key needed.
2. **yfinance async wrappers** — `aioyfinance` and similar, but poorly maintained and often broken.

The entire StockLens backend is async FastAPI with asyncpg. Adding a synchronous call would block the event loop.

## Decision

Use `yfinance` wrapped with `asyncio.to_thread()` to run blocking calls in a thread pool executor. Do NOT use any async wrapper library.

```python
# Pattern:
loop = asyncio.get_running_loop()
data = await loop.run_in_executor(None, lambda: yf.download(ticker, ...))
```

## Rationale

- yfinance is battle-tested, actively maintained, and has 15K+ GitHub stars.
- Async wrappers (`aioyfinance`, `yfinance-async`, `asyfinance`) have <500 stars, spotty maintenance, and lag behind yfinance releases.
- `asyncio.to_thread()` is a Python 3.14 stdlib feature — zero dependencies, negligible overhead.
- The overhead of thread pool switching (~100µs) is invisible next to network I/O (100ms+ for yfinance HTTP requests).
- If yfinance is ever deprecated or breaks, only one file (`market/provider.py`) needs rewriting — the DB cache makes the rest of the system resilient.

## Consequences

- Market data requests consume a thread pool slot during yfinance HTTP calls.
- Default thread pool (min(32, os.cpu_count() + 4)) is sufficient for our scale (<10 concurrent data requests).
- All market data endpoints must handle the added latency of yfinance HTTP requests (~200-500ms per ticker).

## Alternatives Considered

| Alternative                         | Reason Rejected                                                       |
| ----------------------------------- | --------------------------------------------------------------------- |
| `aioyfinance`                       | <200 stars, stale, lagging behind yfinance releases                   |
| `yfinance` + monkey-patch `aiohttp` | Unpredictable, unsupported, fragile                                   |
| Direct Yahoo Finance API calls      | No maintained parser for response format, yfinance handles the quirks |
| Alpha Vantage / IEX Cloud / Polygon | Requires API key, monthly cost, no free tier for our volume           |

---

## Postscript (2026-06-30): Tenacity Retry Added

During Phase 2 planning, yfinance error handling was upgraded: both `_download_ohlcv` and `_fetch_quote` now use tenacity retry with exponential backoff (3 attempts, 1s/2s/4s waits). This mitigates Yahoo Finance rate limiting without changing the core wrapping strategy.
