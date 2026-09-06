# ADR 010: GraphQL Read Facade over a Shared Read Layer

**Date:** ​2026-09-04
**Status:** Accepted
**Phase:** 7 — GraphQL Read Facade

## Context

StockLens's data plumbing (SQL, price-map building, live-quote fetching) lives as router-private underscore helpers — there is no service layer for portfolios/performance/market. A GraphQL retrofit therefore needed a data-access story. Separately, market quotes were the top remaining capability gap: REST polls per request, no streaming. The glossary's promised 1-min Redis quote cache was unimplemented in code.

## Decision

- **Shared read layer.** The router-private read helpers (portfolios, holdings, transactions, cash flows, price-map building, live-quote fetching) are extracted verbatim into per-domain query modules. REST routers and GraphQL resolvers both import them — no behavior change, existing tests as safety net. No service-layer invention — a mechanical move..
- **GraphQL read-only facade (Strawberry).** Resolves over the shared read layer. Ownership per Design Constraint #7: verified at Portfolio resolution, child nodes scope by `portfolio_id`. REST keeps writes/OCR/uploads. JWT auth reused..
- **Streaming quotes via Redis pub/sub.** One subscription (`marketQuote(symbol:)`), fed by a 60s poller. The now-implemented 1-min Redis quote cache doubles asthe last-value store, replayed to subscribers on connect. Delivery: at-most-once per tick, no per-client backpressure at current scale (ceiling noted in code comment). Honest framing: near-real-time, ~15-min-delayed Yahoo data — never "live"..
- **Why subscriptions over SSE.** The stream is a typed, schema-integrated contract — same schema/codegen/authz/introspection as queries — whereas an SSE quote endpoint would be a second, untyped contract alongside REST,and would still need the same poller+pub-sub fan-out. Incremental cost of subscriptions = transport only.

## Rationale

- Resolvers must not duplicate ~200 lines of tested SQL/math (drift risk), nor call REST in-process (rate-limiter self-DoS.. A shared layer = one source of truth — "REST = command facade, GraphQL = read facade" becomes code fact, not a talking point..
- The glossary already legislated this design: no-ORM (asyncpg directly,, user-scoped data, 1-min Redis quote cache — all adopted unchanged;the cache was unimplemented, now it exists and serves both REST and the subscription..
- GraphQL subscriptions close the streaming-quotes capability gap while keeping ONE typed contract for the RN app. The agent's 16 curated MCP tools remain untouched — schema introspection is for future consumers, not the current agent..

## Consequences

- `strawberry-graphql` becomes a new runtime dependency..
- Shared read layer extraction touches 4 REST routers — behavior-neutral, validated by the existing test suite..
- REST quote path gains the promised 1-min Redis cache (`get_quote()` = Redis GET → miss → fetch + SETEX 60s) — glossary becomes code-true..
- "Live" claims in README/CV must carry the near-real-time + 15-min-delay caveat..

## Alternatives Considered

| Alternative                              | Reason Rejected                                                                   |
| ---------------------------------------- | --------------------------------------------------------------------------------- |
| Resolvers duplicate router SQL/math      | ~200 lines of drift risk — the exact sin interviewers probe                       |
| Resolvers call REST endpoints in-process | Own rate limiter self-DoS + double serialization                                  |
| SSE quote endpoint                       | Second, untyped contract alongside REST — still needs same poller+pub-sub fan-out |
| Generic GraphQL MCP tool for the agent   | 16 curated tools beat it — burns agent tokens on query construction               |
