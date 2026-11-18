# ADR 011: Server-Computed Portfolio Valuation, Deterministic Codegen, Request Limits

**Date:** 2026-11-18
**Status:** Accepted
**Supersedes in part:** ADR-010 (adds a second subscription; the read-facade decision stands)

## Context

ADR-010 shipped a read facade and one `marketQuote(ticker)` subscription. Three
problems surfaced in review:

1. **The codegen chain was unverified.** `schema.py → schema.graphql → generated.ts`
   had two manual steps and no check. The committed `generated.ts` predated the
   `@graphql-codegen` majors pinned in `package-lock.json`, so the file was not
   reproducible from the toolchain.
2. **The client still did the math.** `quoteMerge.ts` recomputed market value,
   P&L, day change, and weights per tick — a second implementation of the backend
   formulas, and it ignored FX (it assumed GBP prices), which is wrong for
   non-GBP holdings.
3. **No request-cost bounds.** Arbitrary depth, alias bombs, and unbounded
   execution time were all accepted.

## Decision

### 1. Make the codegen chain deterministic and guarded

- Pin `avoidOptionals: true` and `skipTypename: true` in `codegen.yml` so plugin
  majors cannot silently reshape types. Regenerate `generated.ts` from the
  lockfile toolchain.
- `backend/tests/test_graphql_schema_sync.py` compares the **parsed** schemas
  (`schema.py` vs `schema.graphql`), so formatting differences are ignored and
  only real drift fails.
- The CI lint job regenerates `generated.ts` from `schema.graphql` + the
  `.graphql` documents, formats it, and fails on any diff.

### 2. Compute the valuation on the server

- New subscription `portfolioValuation(portfolioId)`, emitting totals + holdings
  with FX applied, weights, day change, and P&L — the same formulas as the full
  performance path, reusing `compute_holding_performance`.
- **TWR is intentionally omitted.** It needs a year of stored price history; a
  60s tick must not run OHLCV coverage. Clients keep TWR from the initial
  `portfolio.performance` query.
- The client subscribes once per portfolio and overlays the payload
  (`applyValuation`). `quoteMerge.ts` and its per-tick math are deleted.
- `marketQuote(ticker)` is retained: it is a generic market primitive and the
  quote cache/poller is shared.
- Ownership is re-verified by `get_portfolio_valuation` on every tick, so a
  transferred or deleted portfolio stops streaming.

### 3. Bound request cost

| Limit             | Value | Why                                        |
| ----------------- | ----- | ------------------------------------------ |
| Max query depth   | 10    | Schema's deepest legal query is ~4         |
| Max aliases       | 50    | Blocks alias-amplification                 |
| Execute timeout   | 30s   | Query/mutation only — subscriptions exempt |
| Parser/validation | cache | Mobile clients resend identical documents  |

Backing off a request returns a normal GraphQL error (`Query timed out`,
`exceeds maximum operation depth`), not a 500.

## Consequences

- One subscription replaces N per-ticker streams; derived values are FX-correct
  and computed once per portfolio per tick.
- Per tick: one ownership check, one holdings read, one cash-balance read, and
  Redis-cached quotes per portfolio. Acceptable at current scale; noted in code.
- The 60s cadence and ~15-minute Yahoo delay are unchanged: still
  near-real-time, never "live".
- The subscriber registry remains in-process (single replica). Multi-replica
  needs a Redis-backed registry — unchanged from ADR-010.
- A schema change now requires regenerating both `schema.graphql` and
  `generated.ts`; CI enforces it.

## Alternatives Considered

| Alternative                                   | Why rejected                                                                  |
| --------------------------------------------- | ----------------------------------------------------------------------------- |
| Keep client-side merge, add FX to the client  | Duplicates backend math and drifts; the server already owns the formulas      |
| Add a `portfolioPerformance` subscription     | Runs TWR/OHLCV work every 60s for no user-visible freshness gain              |
| Delete `marketQuote` once the screen migrates | It is a generic primitive; removing it would shrink a tested public surface   |
| Persisted queries (APQ) now                   | Single first-party client; build/server coordination outweighs the benefit    |
| Raw `diff` for schema drift                   | Committed SDL is formatted differently from `as_str()`; parse-compare instead |
