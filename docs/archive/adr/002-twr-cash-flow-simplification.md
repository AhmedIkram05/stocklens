# ADR 002: TWR Cash Flow Simplification Using Transaction Data

**Date:** 2026-06-30
**Status:** Accepted
**Phase:** 2 — Market Data Layer

## Context

Time-Weighted Return (TWR) requires knowledge of external cash flows (deposits/withdrawals to/from the portfolio). The current data model has:

- `transactions` — BUY/SELL records (`total_amount`, `date`, `ticker`, `shares`, `price_per_share`)
- `holdings` — current positions (`shares`, `average_cost_basis`)
- No `cash_balance` table — the app does not track uninvested cash
- No `portfolio_deposits` or `portfolio_withdrawals` table

Without tracking external cash flows separately, TWR calculation is ambiguous.

## Decision

Treat every BUY transaction as an external cash inflow (deposit) and every SELL transaction as an external cash outflow (withdrawal) for TWR calculation purposes. Document this simplification clearly in the API response.

```python
# Simplified cash flow mapping:
# BUY  → CF += total_amount  (cash enters the portfolio to buy shares)
# SELL → CF -= total_amount  (cash leaves the portfolio from selling shares)
```

The TWR sub-period formula becomes:

```
r_i = (EMV_i - BMV_i - CF_i) / BMV_i
```

Where `CF_i` = sum of BUY total_amounts − sum of SELL total_amounts during sub-period `i`.

## Rationale

- Adding a `cash_balance` table or `portfolio_cash_flows` table would require a new migration, new CRUD endpoints, and UI changes — all outside Phase 2 scope.
- For buy-and-hold investors (the primary user persona), every BUY effectively creates a new cash inflow (money newly allocated to the portfolio).
- The simplification is conservative: it slightly understates returns during accumulation (buys are counted as fresh deposits, reducing the TWR vs. attributing growth to existing capital).
- The simplification is clearly documentable in the API response (`twr_methodology: "transaction-based"` or similar field).

## Consequences

- TWR will differ from a "true" TWR that tracks actual deposits/withdrawals.
- Users who sell a holding and buy another will see a withdrawal (SELL) followed by a deposit (BUY), which cancels out in the sub-period return calculation — correct behavior.
- A future Phase can add `portfolio_cash_flows` table and switch TWR calculation to use it, adding a `methodology: "actual"` option alongside the current `"transaction-based"` methodology.
- API response includes `methodology` field so users and frontend understand the simplification.

## Alternatives Considered

| Alternative                               | Reason Rejected                                                                      |
| ----------------------------------------- | ------------------------------------------------------------------------------------ |
| Track actual deposits via separate table  | Scope creep — requires new schema, CRUD, and frontend work                           |
| Skip TWR entirely, use Simple Return only | TWR is the industry standard for portfolio performance; omitting it reduces CV value |
| Infer cash flows from share count changes | Complex, fragile, and still ambiguous (needs price data for every day)               |

---

## Postscript (2026-06-30): Updated Decision — Explicit Cash Flows Table

During Phase 2 planning review, the business model was clarified: the app is a paper trading simulator where scanning a receipt deposits play money. This changes the cash flow model:

- **Cash flows are now explicit** — a `cash_flows` table (`id`, `portfolio_id`, `amount`, `source`, `source_id`, `notes`, `created_at`) was added in migration 0003.
- **Receipt scan → cash flow** — scanning a receipt creates a `cash_flows` record with `source='receipt'` and `source_id=receipt.id`.
- **Transactions are holdings-only** — TWR no longer infers CF from BUY/SELL amounts. Cash flows and transactions are separate signals: cash_flows → external CF amounts, transactions → holdings state (BMV/EMV).
- **Free cash balance** — `SUM(cash_flows.amount) - SUM(BUY total_amount) + SUM(SELL total_amount)` tracks uninvested cash.

### Rationale for the Change

- **Receipts as deposits** was a simpler model than anticipated. No withdrawal flow means cash_flows are always positive, and TWR only processes deposits.
- **Cleaner math** — separating external CF from holdings state removes the ambiguity of inferring one from the other. Sub-period formula unchanged (`r = (EMV - BMV - CF) / BMV`).
- **API cleaner** — `twr_methodology: "cash-flow-based"` is more intuitive than "transaction-based."

### What Stayed the Same

- Sub-period return formula is identical.
- BMV=0 guard unchanged.
- Annualisation unchanged.
- The core simplification (no real-world bank transfers, no dividend tracking, no corporate action adjustments) still applies.
