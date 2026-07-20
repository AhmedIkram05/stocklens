# Implementation Plan: Multi-Currency Support (Base = GBP)

## Overview

Stocks trade in USD/EUR/GBP but the app treats all money as homogeneous GBP, which
silently corrupts affordability checks, free-cash, portfolio market value, and
cross-ticker return comparisons whenever a non-GBP holding exists. We store **native
values + a parallel `*_gbp` normalized column + `currency` + `fx_rate_to_gbp`** on
`transactions` and `holdings`, plus an `instruments` table for per-ticker market
currency. All user-facing aggregates are converted to GBP at the point of use.
Receipts stay GBP-only. Prediction/drift code is untouched (ratio-based,
currency-agnostic).

## Constraints / Decisions

- Base currency is **fixed GBP**. `fx_rate_to_gbp` = GBP per 1 unit of native currency
  (GBP=1). For native `C` we fetch yfinance `GBP{C}=X` (= `C` per GBP) and invert.
- **Use TODAY's fx rate everywhere.** No historical FX series, no per-date lookup.
  Simplification agreed with user: GBP aggregates use the latest available rate for both
  point-in-time and historical valuations. This ignores fx movement over time (acceptable
  for a GBP base user; corrects the _magnitude_ error, not the _timing_ of currency drift).
- **No FX join at query time.** Snapshot `fx_rate_to_gbp` onto each transaction/holding
  row so `SUM(..._gbp)` works. Keeps every existing SQL aggregate intact.
- Currency is resolved **server-side** from ticker (never trusted from client).
- Receipts: GBP-only. Cheap nice-extra: reject `$`/`€` OCR with a "enter in £" prompt.

## Requirements

- Buying/selling a USD/EUR stock stores its native price + GBP equivalent; affordability
  and free-cash use GBP.
- Portfolio market value / cost basis / unrealised P&L shown in GBP even with mixed
  currencies.
- Stock-returns (TWR / daily / benchmark) comparisons correct in GBP.
- Receipts never accept non-GBP.

## Schema Changes (Alembic migrations)

There is **no migrations folder yet** — `run_migrations()` runs `alembic upgrade head`
at startup, and `schema.py` is the autogenerate target. First migration must be hand-
written (Alembic env not yet scaffolded under `migrations/`). Steps add columns + one
new table + a data backfill.

1. **New table `instruments`** (File: `backend/alembic/versions/0001_instruments.py`):
   - `ticker` VARCHAR(10) PK, `currency` VARCHAR(3) NOT NULL DEFAULT 'GBP',
     `exchange` VARCHAR(20), `updated_at` timestamptz default now().
2. **`transactions`** add columns: `currency` VARCHAR(3) NOT NULL DEFAULT 'GBP',
   `fx_rate_to_gbp` NUMERIC(24,10) NOT NULL DEFAULT 1,
   `total_amount_gbp` NUMERIC(24,6) NOT NULL DEFAULT 0.
   - Backfill in same migration: `UPDATE transactions SET currency='GBP',
fx_rate_to_gbp=1, total_amount_gbp=total_amount;` (legacy rows assumed GBP).
   - Native `CheckConstraint total_amount = shares*price_per_share` stays unchanged.
3. **`holdings`** add columns: `currency` VARCHAR(3) NOT NULL DEFAULT 'GBP',
   `fx_rate_to_gbp` NUMERIC(24,10) NOT NULL DEFAULT 1,
   `average_cost_basis_gbp` NUMERIC(12,4) NOT NULL DEFAULT 0.
   - Backfill: `UPDATE holdings SET average_cost_basis_gbp = average_cost_basis;`
4. **`schema.py`** (File: `backend/src/database/schema.py`): mirror the 3 changes above
   into the `Table` definitions so future autogenerate diffs stay clean.
5. **Alembic env** scaffold: create `backend/alembic/env.py` + `script.py.mako` if
   absent (check first — `alembic.ini` exists but no `versions/`). If no env exists,
   generate via `alembic init` then trim to asyncpg DSN from `settings.DATABASE_URL`.

## Architecture Changes

- New helper `resolve_instrument(ticker)` (File: `backend/src/market/fx.py`):
  - SELECT currency/exchange FROM instruments; if missing → `fetch_quote(ticker)`,
    read `info['currency']`/`info['exchange']`, UPSERT into instruments, return.
- New helper `get_fx_rate_to_gbp(currency)` (File: `backend/src/market/fx.py`):
  - `'GBP'` → `Decimal('1')`.
  - Else fetch `yf.download(f"GBP{currency}=X")` latest close in provider
    (add `fetch_fx()` to `market/provider.py`); `fx = 1 / rate`.
  - Cache in Redis (mirror quote cache pattern in `market/router.py`). No date arg —
    always today's rate.
- `fetch_quote` (provider) additionally returns `currency`, `exchange`.

## Implementation Steps

### Phase 1 — Storage + correctness for buy/sell (MVP, independently shippable)

1. **Scaffold Alembic + migration 0001** (files above). Verify
   `run_migrations()` applies on startup/tests.
2. **`market/provider.py`** `fetch_quote`: add `currency = info.get("currency")`,
   `exchange = info.get("exchange")` to returned dict. Add `fetch_fx(currency)` returning
   the latest `GBP{c}=X` close (used by `get_fx_rate_to_gbp`).
3. **`market/fx.py`** `resolve_instrument` + `get_fx_rate_to_gbp` (Redis-cached).
4. **`market/schemas.py` + `market/router.py`**: add `currency: str` and `exchange: str | None`
   to `QuoteResponse`; pass through from `fetch_quote` dict in the `/quote/{ticker}` handler.
5. **`transactions/schemas.py`**: add `currency: str | None = None` to
   `TransactionResponse`; keep `Create` without currency (server-resolved).
6. **`transactions/router.py` create_transaction** (the core fix):
   - After portfolio check, `currency = await resolve_instrument(ticker)['currency']`.
   - `fx = await get_fx_rate_to_gbp(currency)`.
   - `total_amount_gbp = total_amount * fx`.
   - Affordability guard: compute `net_invested_gbp = SUM(total_amount_gbp ...)` and
     compare `total_amount_gbp > (deposits - net_invested_gbp)`.
   - INSERT adds `currency, fx_rate_to_gbp, total_amount_gbp`.
   - Pass `currency, fx, total_amount_gbp` into `_apply_buy_to_holdings` /
     `_apply_sell_to_holdings`.
   - `_apply_buy_to_holdings`: INSERT/UPDATE holding with `currency`,
     `fx_rate_to_gbp=fx`, `average_cost_basis_gbp = new_cost * fx`.
7. **`_row_to_response`**: include `currency`.
8. **`holdings/router.py` create_holding**: resolve `currency` from instrument (fallback
   'GBP'), store `currency, fx_rate_to_gbp, average_cost_basis_gbp`.

### Phase 2 — Portfolio performance in GBP

8. **`performance/router.py` `_get_free_cash_balance`**: use `SUM(total_amount_gbp)`
   instead of `SUM(total_amount)` for net invested; deposits stay GBP.
9. **`performance/calculations.py` `compute_holding_performance`**: `market_value` and
   `day_change` computed from `current_price_native * fx_today`; `cost_basis` from
   `shares * average_cost_basis_gbp`; P&L in GBP.
10. **`performance/router.py` price_map**: also carry per-ticker `fx_today`; market
    value GBP = `shares * adjusted_close_native * fx_today`.
11. **`performance/calculations.py` `compute_portfolio_performance`**: sum the `*_gbp`
    fields; `total_market_value`/`total_cost_basis` now valid GBP across currencies.

### Phase 3 — TWR / returns in GBP (today's fx only)

12. **`performance/router.py` `_compute_portfolio_daily_returns`**: for each holding,
    convert each date's native valuation to GBP via `get_fx_rate_to_gbp(currency)`
    (today's rate, single call per distinct currency, Redis-cached). Per-ticker return
    ratios are currency-agnostic; the GBP combination is now correct in magnitude.
    No historical FX — fx drift over the window is not modelled (intentional
    simplification, agreed with user).
13. **Benchmark comparison**: per-ticker ratio series, currency-agnostic — no change
    beyond ensuring the portfolio leg uses GBP valuations from step 12.

### Phase 4 — Receipts GBP guard + frontend

14. **`frontend/src/services/receiptParser.ts`** (cheap nice-extra): if `hasCurrency`
    regex matches `$` or `€`, return an error/blank amount with a flag
    `unsupportedCurrency: true`; surface "This app only supports £ receipts." in
    `ScanScreen`/`ReceiptDetailsScreen`. Do NOT persist non-GBP.
15. **`market/schemas.py` + frontend `market.ts`**: add `currency` to `QuoteData`;
    `TradeScreen.tsx` shows `quote.currency` symbol instead of hardcoded `$` in the
    preview row (lines 259, 298).
16. **`frontend/src/services/portfolios.ts`**: add `currency` to `Transaction`,
    `Holding`, `HoldingPerformance`; backend responses already include it (steps 6, 11).
17. **`formatters.ts`**: add `formatCurrency(amount, currency='GBP')` that uses the
    passed currency; keep `formatCurrencyGBP` as thin wrapper. Replace hardcoded GBP
    money display in `HomeScreen`, `PortfolioListScreen`, `PortfolioDetailScreen`,
    `DepositScreen`, `ReceiptDetailsScreen` where it shows holding/transaction values
    with `formatCurrency(value, holding.currency)` so a $ stock shows `$`.
`ponytail:` aggregate portfolio totals (total market value, free cash, P&L sums)
    stay GBP (no currency arg) — they are already GBP-normalized backend-side.

## Testing Strategy

- Unit: `market/fx.py` `get_fx_rate_to_gbp` (GBP→1, USD→inverted from GBPUSD=X),
  `resolve_instrument` caching.
- Backend tests (existing `tests/`): extend transaction create test to BUY a USD ticker
  (e.g. AAPL) and assert `currency='USD'`, `total_amount_gbp ≈ total_amount*fx`,
  and affordability guard uses GBP (buy $1000 stock with £500 deposit → rejected).
- Performance tests: portfolio with one GBP + one USD holding → assert
  `total_market_value` ≈ GBP sum, `free_cash_balance` correct.
- Frontend: `receiptParser` rejects `€/$`; TradeScreen preview shows ticker currency.
- **E2E** (new `tests/e2e/test_currency_flow.py`): as one user —
  1. Deposit £1000 (cash_flow GBP).
  2. BUY 10 AAPL @ $150 (USD) → assert `transactions.currency='USD'`,
     `total_amount_gbp ≈ 1500 * fx_usd`, `instruments` row AAPL currency=USD.
  3. BUY 5 SHEL @ £20 (GBP) → `currency='GBP'`, `total_amount_gbp=100`.
  4. `GET /portfolio/performance/{id}` → `free_cash_balance ≈ 1000 - (1500*fx_usd + 100)`,
     `total_market_value` ≈ GBP sum, holdings carry their own `currency`.
  5. `GET /portfolio/benchmark/{id}` returns a number (no crash) with mixed currencies.
  6. Scan a receipt whose OCR contains `€` → rejected with "enter in £" message.

## Risks & Mitigations

- **Risk**: yfinance FX/no-currency for thinly-traded tickers.
  - Mitigation: default currency 'GBP', fx 1; log unknown; never crash the trade.
- **Risk**: TWR uses today's fx for all historical dates → ignores fx drift over the
  window.
  - Mitigation: intentional, agreed with user. Magnitude (cross-currency sum) is correct;
    timing of currency moves is not modelled. Revisit only if GBP fx volatility becomes
    material to reported returns.
- **Risk**: backfill assumes legacy rows are GBP.
  - Mitigation: explicit, documented; only wrong for pre-existing foreign trades
    (none expected — app was single-currency). Correctable later via re-fetch.
- **Risk**: two holding write paths diverge on currency.
  - Mitigation: both resolve currency from `instruments`; shared helper.

## Success Criteria

- [ ] Buying a USD/EUR stock stores native + GBP; affordability + free cash in GBP.
- [ ] Portfolio total market value / cost basis / P&L correct with mixed currencies.
- [ ] TWR / daily / benchmark comparisons correct in GBP.
- [ ] Receipts reject non-GBP with a clear prompt.
- [ ] All existing tests pass; new currency tests pass; `run_migrations` clean.
