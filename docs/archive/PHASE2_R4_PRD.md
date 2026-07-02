# Phase 2, Round 4 — PRD: Full Portfolio UX Frontend

> **Product Requirements Document**
> **Project:** StockLens
> **Phase:** 2 (Round 4)
> **Status:** Draft
> **Date:** 2026-07-01

---

## 1. Overview

### 1.1 Problem

The app has a projections-only UI: users scan receipts and see "what if you invested instead?" using preset CAGR rates. Phase 2 built the backend for real portfolio management (holdings, transactions, deposits, P&L, TWR, benchmark comparison), but the frontend still talks to Alpha Vantage directly and has no portfolio screens.

### 1.2 Goal

Replace the Alpha Vantage data pipeline with the backend `/market/` endpoints and build a complete portfolio management UX: create portfolios, deposit via receipt, record buys/sells, view holdings with P&L, and compare performance against benchmarks. Remove ~500 lines of dead Alpha Vantage code.

### 1.3 Success Criteria

- User can create a portfolio, deposit money via receipt, buy/sell stocks, see holdings with real P&L, and compare against SPY/QQQ
- All market data flows through backend `/market/` endpoints (no direct AV calls)
- All existing Jest tests pass
- `npx tsc --noEmit` — zero errors
- ESLint — zero errors
- 8 new unit test files for services + screens

---

## 2. Backend API Surface

All endpoints already exist. Frontend needs typed methods for each.

| Module       | Method   | Endpoint                                | Purpose                         |
| ------------ | -------- | --------------------------------------- | ------------------------------- |
| Portfolio    | GET      | `/portfolios`                           | List user's portfolios          |
| Portfolio    | POST     | `/portfolios`                           | Create portfolio                |
| Portfolio    | GET      | `/portfolios/{id}`                      | Get portfolio detail            |
| Portfolio    | PUT      | `/portfolios/{id}`                      | Update portfolio                |
| Portfolio    | DELETE   | `/portfolios/{id}`                      | Delete portfolio                |
| Holdings     | GET      | `/portfolios/{id}/holdings`             | List holdings                   |
| Holdings     | POST     | `/portfolios/{id}/holdings`             | Add holding                     |
| Holdings     | PUT      | `/holdings/{id}`                        | Update holding                  |
| Holdings     | DELETE   | `/holdings/{id}`                        | Delete holding                  |
| Transactions | GET      | `/portfolios/{id}/transactions`         | List transactions               |
| Transactions | POST     | `/portfolios/{id}/transactions`         | Record transaction              |
| Cash Flows   | GET      | `/portfolios/{id}/cash-flows`           | List cash flows                 |
| Cash Flows   | POST     | `/portfolios/{id}/cash-flows`           | Create deposit                  |
| Cash Flows   | PATCH    | `/portfolios/{id}/cash-flows/{cf_id}`   | Update notes                    |
| Market       | GET      | `/market/ohlcv/{ticker}`                | Historical OHLCV                |
| Market       | GET      | `/market/quote/{ticker}`                | Current quote                   |
| Performance  | GET      | `/portfolio/performance/{portfolio_id}` | P&L + TWR                       |
| Performance  | GET      | `/portfolio/benchmark/{portfolio_id}`   | Benchmark comparison            |
| Receipts     | GET/POST | `/receipts`                             | List/create receipts (existing) |
| Receipts     | GET      | `/receipts/{id}`                        | Get receipt (existing)          |

---

## 3. Data Flow

```
Before (current):
  Screen → dataService → alphaVantageService → AV API (direct)
  Screen → projectionService → dataService → AV API

After (R4):
  Screen → portfolioService → api.ts → FastAPI → PostgreSQL
  Screen → marketService → api.ts → FastAPI → yfinance (cached in PG)
  Screen → receipts (existing) → api.ts → FastAPI
```

---

## 4. Deliverables

### 4.1 — API Service Files (2 files)

#### `src/services/portfolios.ts`

Typed methods wrapping `api.ts`, following `receipts.ts` pattern.

```typescript
// Core CRUD
listPortfolios(): Promise<Portfolio[]>
getPortfolio(id: number): Promise<Portfolio>
createPortfolio(data: CreatePortfolio): Promise<Portfolio>
updatePortfolio(id: number, data: UpdatePortfolio): Promise<Portfolio>
deletePortfolio(id: number): Promise<void>

// Holdings
listHoldings(portfolioId: number): Promise<Holding[]>
createHolding(portfolioId: number, data: CreateHolding): Promise<Holding>
updateHolding(id: number, data: UpdateHolding): Promise<Holding>
deleteHolding(id: number): Promise<void>

// Transactions
listTransactions(portfolioId: number): Promise<Transaction[]>
createTransaction(portfolioId: number, data: CreateTransaction): Promise<Transaction>

// Cash Flows
listCashFlows(portfolioId: number): Promise<CashFlow[]>
createCashFlow(portfolioId: number, data: CreateCashFlow): Promise<CashFlow>
updateCashFlowNotes(portfolioId: number, cfId: number, notes: string): Promise<CashFlow>

// Performance
getPerformance(portfolioId: number): Promise<PortfolioPerformance>
getBenchmark(portfolioId: number, benchmarkTicker?: string): Promise<BenchmarkComparison>
```

#### `src/services/market.ts`

Replaces `dataService.ts`. Thin wrapper over `/market/` endpoints.

```typescript
getOHLCV(ticker: string, startDate?: string, endDate?: string): Promise<OHLCVData[]>
getQuote(ticker: string): Promise<QuoteData>
```

### 4.2 — Screen: Portfolio List (`src/screens/portfolio/PortfolioListScreen.tsx`)

**UI:**

- Header: "My Portfolios" + "+" FAB
- Cards: name, total value, P&L (colored green/red), last updated
- Empty state: "No portfolios yet. Tap + to create one."
- Pull-to-refresh

**Data:** `listPortfolios()` → for each, optionally call `getPerformance()` to show P&L

**Navigation:** Tapping a card → PortfolioDetail. Tapping "+" → CreatePortfolio.

### 4.3 — Screen: Portfolio Detail (`src/screens/portfolio/PortfolioDetailScreen.tsx`)

**UI:**

- Header: portfolio name, total value, TWR %
- Holdings table: ticker, shares, avg cost, current price, market value, P&L $/%, weight
- Footer: cash balance
- Action buttons: [+Deposit] [+Buy] [Sell] [Benchmark]

**Data:** `getPortfolio(id)` → `listHoldings(id)` → `getPerformance(id)` for P&L/TWR

### 4.4 — Screen: Deposit (`src/screens/portfolio/DepositScreen.tsx`)

**UI:**

- Option A: "Scan Receipt" — launches existing ScanScreen flow, shows latest receipts, pick one → amount auto-fills
- Option B: "Manual Entry" — amount input + optional notes
- Confirm button → creates cash_flow

**Data:** `createCashFlow(portfolioId, { amount, source: 'receipt'|'manual', source_id?, notes })`

**Edge cases:**

- Receipt already linked to a cash_flow → hide from picker
- Amount must be > 0

### 4.5 — Screen: Buy/Sell (`src/screens/portfolio/TradeScreen.tsx`)

**UI (single screen toggles between Buy/Sell):**

- Ticker search/input (auto-uppercase, validate against `/market/quote/`)
- Shares input (decimal allowed for fractional)
- Toggle: Buy / Sell
- Preview row: ticker × shares @ current price = total
- Confirm button

**Data:** `createTransaction(portfolioId, { ticker, shares, price, transaction_type: 'buy'|'sell', date })`

**Edge cases:**

- Sell > owned shares → validate against holding.shares
- Buy ticker that doesn't exist → show quote preview before confirming

### 4.6 — Screen: Benchmark Comparison (`src/screens/portfolio/BenchmarkScreen.tsx`)

**UI:**

- Header: "Benchmark Comparison"
- Two-line chart: portfolio TWR vs SPY (or QQQ picker)
- Stats cards: Alpha (excess return), Tracking Error, Information Ratio
- Info section explaining each metric

**Data:** `getBenchmark(portfolioId, benchmarkTicker)` — picks default SPY

### 4.7 — Screen: Create Portfolio (`src/screens/portfolio/CreatePortfolioScreen.tsx`)

**UI (modal form):**

- Name (required)
- Optional: initial deposit amount + source (manual/receipt)

**Data:** `createPortfolio({ name })` → if deposit > 0, `createCashFlow(newId, { amount })`

### 4.8 — Navigation Update

**Before:** 4 tabs: Dashboard | Scan | Summary | Settings

**After:** 5 tabs: Dashboard | Portfolio | Scan | Summary | Settings

Portfolio tab → stack navigator:

- PortfolioList
- PortfolioDetail (params: portfolioId)
- Deposit (params: portfolioId)
- Trade (params: portfolioId, mode: 'buy'|'sell')
- Benchmark (params: portfolioId)
- CreatePortfolio (modal)

### 4.9 — Rewrite `dataService.ts`

Collapse `dataService.ts` to a thin re-export from `market.ts`:

```typescript
// dataService.ts — DEPRECATED. Use market.ts instead.
export { getOHLCV, getQuote } from './market';
```

Update `projectionService.ts` to import from `market.ts` instead of `dataService.ts`.

Update `projectionService.ts` CAGR logic to use backend OHLCV data:

```typescript
async function getCAGR(ticker: string): Promise<number | null> {
  const ohlcv = await getOHLCV(ticker);
  if (ohlcv.length < 2) return null;
  const first = ohlcv[0].adjustedClose;
  const last = ohlcv[ohlcv.length - 1].adjustedClose;
  const years = ohlcv.length / 252; // trading days
  return (last / first) ** (1 / years) - 1;
}
```

### 4.10 — Remove Alpha Vantage

Delete these files (no salvageable code):

- `src/services/alphaVantageService.ts`
- `src/services/database.ts`
- `src/services/eventBus.ts` (only used by AV data flow)

Update these files:

- `App.tsx` — remove SQLite init, remove `ensureHistoricalPrefetch()` call
- `src/services/dataService.ts` — rewritten (see 4.9)
- `src/services/projectionService.ts` — use market.ts

Remove these env references (if any in `.env.example` or config):

- `ALPHA_VANTAGE_API_KEY`

### 4.11 — Tests

| File                                                               | Action                                                                                           |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `src/__tests__/services/alphaVantageService.unit.test.ts`          | Delete                                                                                           |
| `src/__tests__/services/dataService.unit.test.ts`                  | Rewrite for market.ts                                                                            |
| `src/__tests__/services/eventBus.unit.test.ts`                     | Delete                                                                                           |
| `src/__tests__/services/projectionService.unit.test.ts`            | Rewrite for market.ts CAGR                                                                       |
| `src/__tests__/fixtures/stocks.ts`                                 | Update — stop importing OHLCV from alphaVantageService, define own type or import from market.ts |
| `src/__tests__/services/portfolios.unit.test.ts`                   | New — test all portfolioService methods                                                          |
| `src/__tests__/services/market.unit.test.ts`                       | New — test marketService methods                                                                 |
| `src/__tests__/screens/PortfolioListScreen.integration.test.tsx`   | New                                                                                              |
| `src/__tests__/screens/PortfolioDetailScreen.integration.test.tsx` | New                                                                                              |
| `src/__tests__/screens/DepositScreen.integration.test.tsx`         | New                                                                                              |
| `src/__tests__/screens/TradeScreen.integration.test.tsx`           | New                                                                                              |
| Update existing screen tests as needed                             | HomeScreen, SummaryScreen (they lose AV/eventBus imports)                                        |

### 4.12 — Verification

```bash
npx jest          # all pass
npx tsc --noEmit  # zero errors
npx eslint src/   # zero errors
```

---

## 5. UI/UX Specifications

### 5.1 Color Coding

- Positive P&L: green (`#34C759`)
- Negative P&L: red (`#FF3B30`)
- Cash/free balance: blue (`#007AFF`)
- Primary action buttons: brand primary (existing `theme.primary`)
- Deposit action: blue
- Buy action: green
- Sell action: red

### 5.2 Responsive Layout

- Use existing `useBreakpoint()` for responsive adjustments
- `ScreenContainer`, `ResponsiveContainer` wrappers (existing pattern)
- Holdings table: scroll horizontally on small screens

### 5.3 Loading & Error States

- Skeleton/shimmer loading while PortfolioList fetches (use `ActivityIndicator` — existing pattern)
- Pull-to-refresh on list and detail screens
- Error banner if a service call fails (inline, not toast)
- Offline: show cached data if available, disable mutation buttons

### 5.4 Empty States

- Portfolio list: "No portfolios yet" + "Create Your First Portfolio" CTA
- Holdings: "No holdings yet. Tap Buy to get started."
- Transactions: "No transactions recorded."
- Benchmark: "Add holdings and prices to see benchmark comparison."
- Deposit: "Select a receipt or enter an amount manually."

---

## 6. Dependencies

None. All data comes through `api.ts` → existing FastAPI. No new npm packages.

---

## 7. Risks & Mitigations

| Risk                                            | Impact                           | Mitigation                                                                             |
| ----------------------------------------------- | -------------------------------- | -------------------------------------------------------------------------------------- |
| Receipt-to-cash_flow linking creates duplicates | User deposits same receipt twice | Track `receipt_used` boolean or check `source_id` uniqueness before creating cash_flow |
| Sell > owned shares                             | Failed transaction               | Frontend validates against holding.shares before POST                                  |
| Market data stale (weekend)                     | Wrong P&L                        | Backend handles 3-day weekend tolerance; frontend shows last updated timestamp         |
| Navigation complexity with nested stacks        | Broken back navigation           | Use existing `CompositeNavigationProp` pattern (see HomeScreen)                        |
| TWR calculation needs cash flows > 0            | Divide by zero                   | Backend has BMV=0 guard; frontend shows "N/A" if no data                               |

---

## 8. Implementation Order

```
Week 1:
  [4.1]  Typed API services (portfolios.ts, market.ts) — everything depends on these
  [4.8]  Navigation update — route skeleton first
  [4.7]  CreatePortfolioScreen — simple form, feeds portfolios.ts
  [4.2]  PortfolioListScreen — list + pull-to-refresh

Week 2:
  [4.3]  PortfolioDetailScreen — holdings + P&L
  [4.4]  DepositScreen — receipt → cash_flow
  [4.5]  TradeScreen — buy/sell

Week 3:
  [4.6]  BenchmarkScreen — chart + metrics
  [4.9]  Rewrite dataService.ts + projectionService.ts
  [4.10] Remove Alpha Vantage files + cleanup
  [4.11] Tests
  [4.12] Verification pass
```

---

## 9. Key Decisions

### 9.1 Portfolio screens directory

All portfolio screens live in `src/screens/portfolio/`:

- `PortfolioListScreen.tsx`
- `PortfolioDetailScreen.tsx`
- `DepositScreen.tsx`
- `TradeScreen.tsx`
- `BenchmarkScreen.tsx`
- `CreatePortfolioScreen.tsx`

### 9.2 Single TradeScreen for Buy/Sell

One screen toggles between buy and sell mode. Both paths call `createTransaction()` with different `transaction_type`. Reduces duplication vs two separate screens.

### 9.3 Market data: backend-first

Frontend never calls yfinance or AV directly. All market data routes through `/market/ohlcv/{ticker}` and `/market/quote/{ticker}`. Backend handles caching, staleness, and retries.

### 9.4 Receipt → cash flow linking

`createCashFlow` receives `source: 'receipt'` and `source_id: receiptId`. Backend does not enforce FK constraint (per Phase 2 spec). Frontend tracks which receipts are already used and hides them from the deposit picker.

### 9.5 TWR on detail screen

`PortfolioPerformanceResponse` includes `twr` and `annualised_twr` fields. Display both with a tooltip/disclosure: "TWR measures your return independent of when you added money."

---

## 10. Appendix: Existing Patterns to Follow

| Pattern                                 | Reference File                                              |
| --------------------------------------- | ----------------------------------------------------------- |
| Typed service wrapping `api.ts`         | `src/services/receipts.ts`                                  |
| Navigation composite types              | `src/screens/HomeScreen.tsx` (CompositeNavigationProp)      |
| Tab + stack navigation structure        | `src/navigation/AppNavigator.tsx`                           |
| Screen skeleton (loading/error/content) | `src/screens/HomeScreen.tsx`                                |
| StatCard / IconValue usage              | `src/screens/HomeScreen.tsx`                                |
| Theme + brandColors                     | `src/contexts/ThemeContext.ts`                              |
| Responsive layout (Breakpoint)          | `src/hooks/useBreakpoint.ts`                                |
| Formatting utils                        | `src/utils/formatters.ts`                                   |
| Integration test example                | `src/__tests__/screens/SettingsScreen.integration.test.tsx` |
| Test render helpers                     | `src/__tests__/utils/renderWithProviders.tsx`               |
| Stock test fixtures (to update)         | `src/__tests__/fixtures/stocks.ts`                          |
