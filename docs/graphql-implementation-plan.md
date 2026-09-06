# Implementation Plan: GraphQL Read Facade over a Shared Read Layer (ADR 010, Phase 7)

Retrofit a read-only GraphQL layer onto the StockLens FastAPI backend: mechanically extract router-private read helpers into per-domain query modules (shared by REST routers and new Strawberry resolvers), implement the promised 1-min Redis quote cache (`get_quote`), expose `Query { portfolios, portfolio(id), market_quote }` + a `market_quote(ticker)` WebSocket subscription fed by a 60s poller via Redis pub/sub, convert ONE frontend screen (PortfolioDetailScreen) from 1 REST poll to 1 GraphQL query + live quote stream via committed-schema codegen, and document the REST=commands / GraphQL=reads split in README. No MCP/agent/write-path changes.

## Locked decisions honored (do not re-litigate)

1. Shared read layer: verbatim extraction, drop leading underscores, zero REST behavior change.
2. `get_quote` = Redis GET `quote:{ticker}` → miss → `fetch_quote` → `SETEX 60s`;REST quote path, `fetch_live_quotes`,and poller all route through it.
3. Strawberry read-only facade at `/graphql`, JWT auth, ownership verified once at portfolio resolution(children scope by `portfolio_id`), dataloaders = existing batch helpers, plus `Query.market_quote`.
  ​​​4. Subscription `market_quote(ticker)` over WS: single shared 60s poller, in-process refcount symbol registry, last-value replay from the cache key, at-most-once delivery, near-real-time framing.
.
4. Consumer: RN app via graphql-codegen from a committed `schema.graphql`;ONE screen converted.
5. Docs: README section only (CONTEXT.md + ADR 010 exist — reference, don't re-plan.

## Phase 0: Prep (verification, dependency pinning, schema-file strategy)

### 0.1 Verify the Strawberry FastAPI integration semantics (blocks everything GraphQL)

- **Files to inspect after install** (read `backend/.venv/lib/python3.13/site-packages/strawberry/fastapi.py`): confirm (a) `GraphQLRouter(schema, context_getter=..., graphql_ide=None, subscription_protocols=(GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL))` exists;(b) whether `context_getter` is invoked via FastAPI `Depends` (→ `Depends(get_current_user)` params resolve, `HTTPException` → HTTP 401/403) or plain-called(→ fallback: manual `get_current_user(request=request, credentials=...)` call inside + auth via middleware);(c)the WS route does **not** run `context_getter`/`Depends`(expected — WS auth lives in the subscription resolver via `connection_params`;confirm).
- **If (b) is Depends-resolved**, use Mechanism A below.**If plain-called**, use Mechanism B (manual call;wrap `HTTPException` → `GraphQLError`;and assert 401 via a tiny ASGI middleware around the mount or accept GraphQL-error 200 + `errors[0]` — pick middleware for REST-parity 401). This is the single highest-uncertainty item;the executor resolves it from source before writing resolver code. Then run a 10-line empirical spike: mount a stub schema, curl /graphql with/without token → assert 401/200 — source-read AND behavior-proof..

### 0.2 Pin dependencies

- **`backend/pyproject.toml`** — add to `[project].dependencies` (floor-pin, matching `fastapi>=0.138.0` convention;latest verified at plan time = `0.327.2`):

  ```toml
  "strawberry-graphql[fastapi]>=0.327.0",
  ```

  Install extra name verified via official docs: `pip install 'strawberry-graphql[fastapi]'` (provides FastAPI + ASGI + websocket support). Rebuild backend image (`docker compose build backend`).
- **Root `package.json`** — add devDependencies (install at repo root, lockfile pins exact): `@graphql-codegen/cli`, `@graphql-codegen/typescript`, `@graphql-codegen/typescript-operations`, `graphql` (peer of codegen). Add scripts:

  ```json
  "graphql:codegen": "graphql-codegen --config codegen.yml",
  "typecheck": "tsc --noEmit"
  ```

- **Frontend `package.json`** — add runtime dep: `graphql-ws` (official GraphQL-over-WebSocket protocol client, RN-WebSocket-compatible, used by §5.4 subscriptionClient)

### 0.3 Committed schema file strategy

- Create **`schema.graphql`** at repo root: hand-maintained SDL mirror of `backend/src/graphql/schema.py` (codegen source — CI-stable, no live introspection). Keep in sync via Phase 6 introspection-diff check.
- Create **`codegen.yml`** (repo root:

  ```yaml
  schema: schema.graphql
  documents: frontend/src/graphql/*.graphql
  generates:
    frontend/src/graphql/generated.ts:
      plugins: [typescript, typescript-operations]
      config:
        scalars:
          Date: string
          DateTime: string
  ```

- **Acceptance:** `npm install` succeeds;`npx graphql-codegen --config codegen.yml` runs (may emit empty generated.ts until Phase 5 adds a document), backend image rebuilds.

---

## Phase 1: Shared Read Layer Extraction (behavior-neutral)

### 1.1 Create `backend/src/portfolios/queries.py` (new)

Move verbatim from `backend/src/portfolios/router.py` (rename: drop `_`):

- `async def fetch_portfolios_from_db(user_id: str) -> list[dict]` — exact SELECT body of `_fetch_portfolios_from_db`.
- `async def fetch_portfolio_by_id(portfolio_id: str, user_id: str) -> dict | None` — exact body of `_fetch_portfolio_by_id`.
- **Not moved** (stay in router): `_row_to_response` (REST-only mapper;GraphQL builds its own type).

### 1.2 Update `backend/src/portfolios/router.py`

- Delete the two moved function bodies;add `from src.portfolios.queries import fetch_portfolios_from_db, fetch_portfolio_by_id`. All routes unchanged (they already call these names).

### 1.3 Create `backend/src/performance/queries.py` (new)

Move verbatim from `backend/src/performance/router.py` (rename: drop `_`):

- `async def verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None`
- `async def get_holdings(portfolio_id: str) -> list[dict[str, Any]]`
- `async def get_transactions_sorted(portfolio_id: str) -> list[dict[str, Any]]`
- `async def get_cash_flows_sorted(portfolio_id: str) -> list[dict[str, Any]]`
- `async def get_free_cash_balance(portfolio_id: str) -> Decimal`
- `async def build_price_map(tickers: list[str], start_date: date, end_date: date, *, limit: int = 50000) -> dict[str, dict[date, Decimal]]`
- `async def fetch_live_quotes(tickers: list[str]) -> dict[str, tuple[Decimal, Decimal]]` — **verbatim now** (calls `provider.fetch_quote` directly;Phase 2 swaps to `get_quote`).
- `async def batch_verify_ownership(portfolio_ids: list[str], user_id: str) -> dict[str, str]`
- `async def batch_get_holdings(portfolio_ids: list[str]) -> dict[str, list[dict[str, Any]]]`
- `async def batch_get_transactions(portfolio_ids: list[str]) -> dict[str, list[dict[str, Any]]]`
- `async def batch_get_cash_flows(portfolio_ids: list[str]) -> dict[str, list[dict[str, Any]]]`
- `async def compute_portfolio_performance_response(portfolio_id: str, portfolio_name: str, start_date: date | None = None, end_date: date | None = None) -> PortfolioPerformanceResponse` —the body of `get_portfolio_performance` **after** the ownership check (defaults, empty-portfolio zero-shape branch, `compute_portfolio_performance(...)` call). **No ownership check** (GraphQL inherits ownership at portfolio resolution — Constraint #7).
- `async def get_portfolio_performance(portfolio_id: str, user_id: str, start_date: date | None = None, end_date: date | None = None) -> PortfolioPerformanceResponse` — `verify_portfolio_ownership` (raise `HTTPException` 404 `"Portfolio not found"`) + call `compute_portfolio_performance_response`. (REST route uses this — byte-identical behavior.)
- `async def get_bulk_portfolio_performance(portfolio_ids: list[str], user_id: str) -> BulkPerformanceResponse` — verbatim body of the bulk route (404 `"No portfolios found for this user"` when none;batch DB reads;one shared `price_map`/`live_quotes`/`fx_rates`;per-pid `compute_portfolio_performance`;empty-pid zero-shape branch).
- `async def compute_benchmark_comparison_response(portfolio_id: str, portfolio_name: str, benchmark: str = "SPY", start_date: date | None = None, end_date: date | None = None) -> BenchmarkComparisonResponse` — body of `_get_benchmark_comparison_inner` **after** ownership check (SPY/QQQ 400 validation, `refresh_ohlcv_if_stale`, coverage fetch/upsert, `build_price_map`, `fetch_live_quotes`, `compute_portfolio_performance`, benchmark daily returns, `_compute_portfolio_daily_returns`, `_cumulative_series`, `compute_benchmark_comparison`).
- `async def get_benchmark_comparison(portfolio_id: str, user_id: str, benchmark: str = "SPY", start_date: date | None = None, end_date: date | None = None) -> BenchmarkComparisonResponse` — verify ownership (404) + call `compute_benchmark_comparison_response`. (REST route uses this.)
- Module-private, moved verbatim (single consumers, keep local): `def _compute_portfolio_daily_returns(...)` and `def _cumulative_series(dates: list[date], returns: list[Decimal]) -> list[dict[str, Any]]`.
- Imports moved with them: `asyncio`, `defaultdict`, date/datetime/timedelta/timezone, `Decimal`, `Any`/`Optional`, `HTTPException`, `settings`, `connection_ctx`, `fetch_ohlcv`, `get_earliest_ohlcv_date`/`get_ohlcv_batch`/`upsert_ohlcv`, `refresh_ohlcv_if_stale` (from `src.market.router` — pre-existing cross-router import pattern), `compute_portfolio_performance`/`compute_benchmark_comparison`, schemas `BenchmarkComparisonResponse`/`BulkPerformanceResponse`/`PortfolioPerformanceResponse`, structlog.

### 1.4 Update `backend/src/performance/router.py`

- Import all moved names from `src.performance.queries`;delete moved defs.
- `get_portfolio_performance` route body → `return await get_portfolio_performance(str(portfolio_id), current_user.id, start_date, end_date)`.
- `bulk_portfolio_performance` route body → parse/validate `portfolio_ids` (unchanged 400), then `return await get_bulk_portfolio_performance(ids, current_user.id)`.

- `get_benchmark_comparison` route stays the try/except logging wrapper;its inner call becomes `return await get_benchmark_comparison(str(portfolio_id), current_user.id, benchmark, start_date, end_date)` (delete `_get_benchmark_comparison_inner`). Catch `HTTPException: raise` / generic → log + re-raise (unchanged).

### 1.5 Behavior-neutrality checklist

- Identical SQL text, identical defaulting(end_date=today, start=365d), identical exception types/messages (404 `"Portfolio not found"`, 400 `"Benchmark must be SPY or QQQ"`, 404 `"No portfolios found for this user"`, 404 `"No price data found for benchmark {benchmark}"`, identical Pydantic response models → byte-identical JSON. `_row_to_response` untouched.

### 1.6 Tests (updates + proof)

- **Existing suites prove it** (must stay green: `backend/tests/test_portfolios.py`, `backend/tests/test_performance.py` (includes direct unit tests of the moved helpers — update import targets below), `backend/tests/test_market.py`.
- **Update `backend/tests/test_performance.py` import/patch targets** (helper identity preserved):
  - `from src.performance.router import _batch_verify_ownership` → `from src.performance.queries import batch_verify_ownership` (3 sites: lines ~994, ~1009, ~1023).
  - `_batch_get_holdings` → `batch_get_holdings` (~1034, ~1057, ~1065);`_batch_get_transactions` → `batch_get_transactions` (~1102, ~1129);`_batch_get_cash_flows` → `batch_get_cash_flows` (~1137, ~1156).
  - `_get_transactions_sorted` → `get_transactions_sorted` (~1279);`_get_cash_flows_sorted` → `get_cash_flows_sorted` (~1301);`_get_free_cash_balance` → `get_free_cash_balance` (~1317.
  - `_fetch_live_quotes` → `fetch_live_quotes` (~1340 — its `mocker.patch("src.performance.router.fetch_quote", ...)` target changes in **Phase 2** to `src.market.quotes.fetch_quote`).
  - `_compute_portfolio_daily_returns` → `_compute_portfolio_daily_returns` stays **module-private in queries.py** → import `from src.performance.queries import _compute_portfolio_daily_returns` (6 sites ~1361–~1495).
  - `_get_benchmark_comparison_inner` → `get_benchmark_comparison` from queries(import ~1545;patch target ~1580 → `"src.performance.queries.get_benchmark_comparison"`).
- **No new tests needed this phase** (existing full suites =the safety net).
- **Verification:** `make test` (docker compose run --rm pytest;service profile auto-enabled by explicit name). Targeted fast-loop:`docker compose run --rm pytest tests/test_portfolios.py tests/test_performance.py tests/test_market.py -q`.
- **Acceptance:** all three suites green;`git diff` of the two routers shows only import swaps + deleted bodies + thin route calls;no SQL/response-shape edits.

---

## Phase 2: 1-min Redis Quote Cache (`get_quote`)

### 2.1 Create `backend/src/market/quotes.py` (new)

```python
QUOTE_CACHE_TTL = 60  # seconds — glossary normative (was 30 in market/router.py; bug fix)
_quote_key = lambda ticker: f"quote:{ticker.upper()}"

async def get_quote(ticker: str) -> dict[str, Any]:
    """Cached quote fetch: Redis GET quote:{ticker} → hit; miss → fetch_quote → SETEX 60s.
    Redis failures log+degrade (never block the fetch);provider failures **propagate** (caller decides: REST 503, poller skip, perf gather-skips. No stale-cache fallback — a stale price can mislead;the 60s TTL already bounds yfinance load."""
    key = _quote_key(ticker)
    try:
        r = await get_redis()
        cached = await r.get(key)
        if cached is not None:
            try: return json.loads(cached)
            except (json.JSONDecodeError, TypeError): logger.warning("quote_cache_corrupt", ticker=ticker.upper())
    except Exception:
        logger.warning("quote_cache_read_failed", ticker=ticker.upper(), exc_info=True)
    quote = await fetch_quote(ticker)   # propagates on provider failure
    try:
        r = await get_redis()
        await r.setex(key, QUOTE_CACHE_TTL, json.dumps(quote, default=str))
    except Exception:
        logger.warning("quote_cache_write_failed", ticker=ticker.upper(), exc_info=True)
    return quote
```

Imports: `json`, `Any`, `structlog`, `from src.cache.redis import get_redis`, `from src.market.provider import fetch_quote`.

### 2.2 Update `backend/src/market/router.py`

- Replace the inline Redis+fetch body of `get_quote_endpoint` with: `quote_data = await get_quote(ticker)` inside the existing try/except → 503 `"Quote temporarily unavailable for {ticker}"` (provider failure propagation preserves 503 behavior). Delete local `QUOTE_CACHE_TTL = 30`, local `get_redis`/`fetch_quote`/`json` imports (if unused elsewhere;keep `fetch_ohlcv` import). Response build unchanged (same field mapping).
- Rename `_refresh_ohlcv_if_stale` → `refresh_ohlcv_if_stale` (drop underscore;body unchanged;update import in `backend/src/performance/queries.py` and any test references — grep shows none direct).

### 2.3 Update `backend/src/performance/queries.py::fetch_live_quotes`

- Swap `tasks = [fetch_quote(t) for t in tickers]` → `tasks = [get_quote(t) for t in tickers]`;import `from src.market.quotes import get_quote`. Shape unchanged (`(result["price"], result["previous_close"])`;gather+return_exceptions+log-skip unchanged). REST performance behavior changes only by adding up-to-60s quote caching (no shape change.

### 2.4 Tests

- **New `backend/tests/test_quote_cache.py`** (patch `src.market.quotes.*`):
  - hit: `mock_redis.get` → cached json;assert parsed quote returned;`fetch_quote` NOT called.
  - miss+set: get → None;`fetch_quote` → QUOTE_DATA;assert `setex(key, 60, json)` called once (TTL **60**).
  - redis-down: `get_redis` raises → falls through to `fetch_quote` → returns data (no raise).
  - corrupt-cache: get → `"not-json"` → refetch fresh.
  - provider-error: `fetch_quote` raises → `get_quote` raises (propagates;REST layer maps 503 — covered by existing `test_yfinance_failure_returns_503` after patch-target update).
- **Update `backend/tests/test_market.py`** quote-endpoint tests — patch targets move (6 sites: `src.market.router.get_redis` → `src.market.quotes.get_redis`;`src.market.router.fetch_quote` → `src.market.quotes.fetch_quote`;lines ~518-519, ~556, ~567-568, ~585-586, ~599-600, ~622-623;and line ~534 TTL assert `30` → `60`). `test_ticker_uppercased` unchanged (get_quote uppercases internally;endpoint keeps its own `.upper()` or drops it — behavior same).
- **Update `backend/tests/test_performance.py`** ~1344 patch target: `"src.performance.router.fetch_quote"` → `"src.market.quotes.fetch_quote"` (fetch_live_quotes → get_quote → quotes-module fetch_quote;`get_redis` unmocked → real Redis (test env) → miss → fetch;if Redis down, graceful-degrade path still reaches fetch).
- **Verification:** `docker compose run --rm pytest tests/test_quote_cache.py tests/test_market.py tests/test_performance.py -q`;then `make test`.
- **Acceptance:** cache hit/miss/expiry(60)/corrupt/redis-down/provider-error covered;REST quote 503 preserved;`get_quote` is the single quote-fetch path for REST + performance (+ poller next phase).

---

## Phase 3: GraphQL Schema + Resolvers (query-only)

### 3.1 Create `backend/src/graphql/__init__.py` (empty

### 3.2 Create `backend/src/graphql/schema.py` (types + resolvers;no Subscription yet — added Phase 4)

**Scalar policy** (REST JSON parity, zero client churn): monetary values = `float` fields (resolver coerces `float(x) if x is not None else None` — matches `DecimalAsFloat`), ids = `strawberry.ID`, dates = `datetime.date` / datetimes = `datetime.datetime` (ISO-8601 strings — identical to Pydantic serialization), enums = `strawberry.enum` (`TransactionType { BUY SELL }`).

**Types** (snake_case field names mirroring REST JSON shapes;all lists/objects non-null unless noted:

- `Query`: `portfolios: list[Portfolio]`, `portfolio(id: strawberry.ID) -> Portfolio | None`, `market_quote(ticker: str) -> Quote`.
- `Portfolio`: `id: ID`, `name: str`, `description: str | None`, `created_at: datetime`, `updated_at: datetime`, `holdings: list[Holding]`, `transactions: list[Transaction]`, `cash_flows: list[CashFlow]`, `performance(startDate: date | None = None, endDate: date | None = None) -> PortfolioPerformance`, `benchmark(benchmark: str = "SPY", startDate: date | None = None,endDate: date | None = None) -> BenchmarkComparison`.
- `Holding`: `id, portfolio_id: ID`, ticker: str`, shares: float`, average_cost_basis: float`, currency: str`, fx_rate_to_gbp: float | None`, average_cost_basis_gbp: float | None` (the 8 columns the holdings query selects).
- `Transaction`: `id: ID, ticker: str, type: TransactionType, shares: float, price_per_share: float, total_amount: float, total_amount_gbp: float | None, date: date` (query renames `transaction_date`→`date`).
- `CashFlow`: `id: ID, portfolio_id: ID`, amount: float`, source: str`, source_id: str | None`, notes: str | None`, created_at: datetime`.
- `Quote`: `ticker: str, price: float | None`, change: float | None`, change_pct: float | None`, previous_close: float | None`, volume: int | None`, currency: str | None`, exchange: str | None`, timestamp: datetime | None`.
- `PortfolioPerformance`: `portfolio_id: ID`, portfolio_name: str`, total_market_value: float | None`, total_cost_basis: float`, total_unrealised_pl: float | None`, total_unrealised_pl_pct: float | None`, day_change: float | None`, day_change_pct: float | None`, free_cash_balance: float`, twr: float | None`, twr_annualised: float | None`, twr_start_date: date | None`, twr_end_date: date | None`, twr_methodology: str`, holdings: list[HoldingPerformance]`, total_holdings: int`, data_quality: str`, calculated_at: datetime` (mirror of `PortfolioPerformanceResponse`).
- `HoldingPerformance`:the 13 fields of `HoldingPerformance` schema (ticker, shares, average_cost_basis, current_price|None, currency, market_value|None, cost_basis, unrealised_pl|None, unrealised_pl_pct|None, day_change|None, day_change_pct|None, portfolio_weight_pct|None — all float.

- `BenchmarkComparison`: mirror of `BenchmarkComparisonResponse` (`portfolio_id: ID, benchmark_ticker: str, portfolio_return: float | None`, benchmark_return: float | None`, excess_return_alpha: float | None`, tracking_error: float | None`, information_ratio: float | None`, period_start: date`, period_end: date`, methodology: str`, daily_returns_count: int`, calculated_at: datetime`, portfolio_cumulative_returns: list[CumulativeReturn]`, benchmark_cumulative_returns: list[CumulativeReturn]`.
- `CumulativeReturn`: `date: date`, value: float`.

**Resolver behaviors** (all read `user_id` from `info.context["user_id"]`):

- `Query.portfolios`: rows = `await fetch_portfolios_from_db(user_id)`;pids = `[str(r["id"]) for r in rows]`. If pids: (a) `bulk = await get_bulk_portfolio_performance(pids, user_id)` (ONE batched compute — mirrors REST bulk exactly:one `price_map`, one `live_quotes`, per-pid compute);(b) **preload children cache** (the dataloader pattern, no extra lib): `info.context["children"] = {pid: {"holdings": batch_get_holdings(pids).get(pid, []), "transactions": batch_get_transactions(pids).get(pid, []), "cash_flows": batch_get_cash_flows(pids).get(pid, []), "performance": bulk.portfolios.get(pid)} for pid in pids}` — 3 batched DB reads + 1 batched compute for N portfolios, **not** N×. Return `[Portfolio(...) for r in rows]`.
- `Query.portfolio(id)`: `row = await fetch_portfolio_by_id(str(id), user_id`;**None → return `None`** (no existence leak — client treats null as "not yours/not found";no HTTP 404 in GraphQL). else `Portfolio.from_row(row)` (no preload — children resolve lazily single-shot;no batch needed for 1).
- `Portfolio.holdings/transactions/cash_flows`: read `info.context["children"][pid]` first;fallback (root-`portfolio(id)` path) → single helper (`get_holdings` etc.). **No ownership re-check** (Constraint #7).
- `Portfolio.performance`: if `startDate is None and endDate is None` and `"performance"` in children-cache → return it (list-query default-dates batch). Else compute single-shot `await compute_portfolio_performance_response(self.id, self.name, startDate, endDate)` (no re-verify — ownership inherited;REST parity via same compute body).
- `Portfolio.benchmark`: `try: return await compute_benchmark_comparison_response(self.id, self.name, benchmark, startDate, endDate);except HTTPException as exc: raise GraphQLError(exc.detail` (`from graphql.error import GraphQLError`) — 400/404 messages surface verbatim in GraphQL errors).
- `Query.market_quote`: `ticker = ticker.upper(); if not re.fullmatch(r"[A-Z0-9.]{1,10}", ticker): raise GraphQLError(f"Invalid ticker: {ticker!r}"); try: q = await get_quote(ticker);except Exception: raise GraphQLError(f"Quote temporarily unavailable for {ticker}")` — REST-503 parity message;map dict→Quote (float-coerce;`timestamp` ISO already).

### 3.3 Create `backend/src/graphql/router.py`

**Mechanism A (primary — confirm in Phase 0;fallback B if context_getter is plain-called):

```python
_limited = limiter.limit(settings.RATE_LIMIT_DEFAULT)(
    async def _noop(request: Request) -> None: return None
)

async def get_graphql_context(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
) -> dict:
    await _limited(request)   # slowapi wrapper raises RateLimitExceeded → app's 429 handler (WS not supported by slowapi — handshake not limited;ceiling comment.

    return {"request": request, "user_id": current_user.id, "children": {}}

graphql_router = GraphQLRouter(
    schema, context_getter=get_graphql_context, graphql_ide=None,
)
```

- **Mechanism B (only if 0.1 shows context_getter is plain-called):** drop `Depends`;manual `credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=request.headers.get("Authorization","").removeprefix("Bearer ").strip()) if "Authorization" in request.headers else None`;`user = await get_current_user(request=request, credentials=credentials)` (raises 401/403 → catch → re-raise so a tiny `@app.middleware("http")`-style wrapper or an ASGI middleware around the `/graphql` mount turns `HTTPException` into the matching status — verify which layer Strawberry propagatesand choose the middleware that yields 401/403 parity with REST).
- Rate limit applies on HTTP only (slowapi has no WS support— README-verified;documented ceiling comment in code: `# ponytail: WS handshake not rate limited;add WS-side limits if abuse appears`).

### 3.4 Mount in `backend/src/main.py`

- In the router-registration zone: `from src.graphql.router import graphql_router  # noqa: E402`;`app.include_router(graphql_router)` (GraphQLRouter's internal path is `/` → served at `/graphql`, HTTP + WS handshake). Place after agent routers. No prefix arg. No lifespan wiring yet (Phase 4.

### 3.5 Tests — new `backend/tests/test_graphql_queries.py`

- **Authz:** POST `/graphql` JSON `{"query": "{ __typename }" }` with no token → **401** (Mechanism A: Depends raises before execution;;B: middleware wrapper). Invalid/garbage token → 401. Valid `auth_headers` → 200 with data.
- **Ownership:** seed another user's portfolio (conftest already seeds pid `22222222-...` owned by user-2): `query { portfolio(id: "22222222-2222-2222-2222-222222222222") { id } }` → `data.portfolio == null` (no leak, no error);`query { portfolios { id } } }` returns only user-1's rows (pid `11111111-...`).
- **Nesting shape:** with holdings+transactions+cash_flows+performance seeded via existing fixture patterns(see test_performance.py helpers): one query fetching `portfolios { id, name, holdings { ticker, shares }, transactions { id, ticker, type }, cash_flows { amount, source }, performance { total_market_value, twr, total_holdings, free_cash_balance } }` → assert exact field values (snake_case names, float money, ISO dates.

- **N+1 batch assertion:** spy on `src.performance.queries.batch_get_holdings` / `batch_get_transactions` / `batch_get_cash_flows` / `get_bulk_portfolio_performance` (patch in the schema module's namespace): run `{ portfolios { id holdings { id } } } }` with 2+ seeded portfolios;assert each batch helper called **exactly once** with all pids (not once-per-portfolio);and `get_bulk_portfolio_performance` called once with all ids. Also assert `performance` subfield on the list query uses the preloaded bulk result (patch `compute_portfolio_performance_response` → assert NOT called when default dates requested).
- **market_quote:** patch `src.market.quotes.get_quote` → canned quote dict;;assert `data.market_quote.price` etc;assert ticker uppercased (call args;;assert invalid ticker (`"abc def"`/empty) → `errors[0].message` contains `"Invalid ticker"`.
- **Errors:** `portfolio(id: "00000000-0000-0000-0000-000000000000")` (nonexistent→ null;`benchmark(benchmark: "TSLA"` → `errors[0].message` contains `"Benchmark must be SPY or QQQ"` (400 parity message).
- **Verification:** `docker compose run --rm pytest tests/test_graphql_queries.py -q`;then `make test`.
- **Acceptance:** auth 401, ownership isolation, nesting parity with REST shapes, dataloader batch asserted(3 batched DB reads + 1 batched compute per list query, marketQuote cached-path works.

---

## Phase 4: Subscription `market_quote(ticker)` + 60s Poller

### 4.1 Create `backend/src/graphql/streaming.py` (new)

```python
_symbol_subscribers: dict[str, int] = {}      # refcounted — 2 clients on same symbol keep it polled
_poller_task: asyncio.Task | None = None
POLL_INTERVAL_SECONDS = 60

def subscribe_symbol(symbol: str) -> None: _symbol_subscribers[symbol] = _symbol_subscribers.get(symbol, 0) + 1
def unsubscribe_symbol(symbol: str) -> None:
    n = _symbol_subscribers.get(symbol, 0) - 1
    if n <= 0: _symbol_subscribers.pop(symbol, None)
    else: _symbol_subscribers[symbol] = n

POLL_FETCH_TIMEOUT_SECONDS =  ​10  # per-symbol cap — provider retries can stall minutes;cadence must survive

async def _fetch_with_timeout(symbol: str) -> dict:
    async with asyncio.timeout(POLL_FETCH_TIMEOUT_SECONDS):
        return await get_quote(symbol)

async def _poller_tick() -> None:
    """One publish round for all actively-subscribed symbols. Exposed for tests."""
    symbols = list(_symbol_subscribers)
    if not symbols: return
    quotes = await asyncio.gather(*[_fetch_with_timeout(s) for s in symbols], return_exceptions=True)
    r = await get_redis()
    for symbol, quote in zip(symbols, quotes):
        if isinstance(quote, Exception): logger.warning("quote_poll_failed", symbol=symbol, error=str(quote));continue
        await r.publish(f"quote:stream:{symbol}", json.dumps(quote, default=str)

async def _poller_loop() -> None:
    while True:
        try: await _poller_tick()
        except Exception: logger.exception("quote_poller_tick_failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

async def start_quote_poller() -> None:  # lifespan
    global _poller_task
    if _poller_task is None: _poller_task = asyncio.create_task(_poller_loop())

async def stop_quote_poller() -> None:
    global _poller_task
    if _poller_task: _poller_task.cancel(); await asyncio.gather(_poller_task, return_exceptions=True); _poller_task = None
```

Ceiling comments in code: `# ponytail: in-process refcount registry;multi-replica would need a Redis-backed registry` and `#at-most-once per tick, no per-client backpressure at this scale;per-client queues if client count grows`.

### 4.2 Extend `backend/src/graphql/schema.py` — Subscription root

- Add `@strawberry.type class Subscription`:

```python
@strawberry.subscription
async def market_quote(self, info: strawberry.Info, ticker: str) -> AsyncGenerator[Quote, None]:
    ticker = ticker.upper()
    if not re.fullmatch(r"[A-Z0-9.]{1,10}", ticker): raise GraphQLError(f"Invalid ticker: {ticker!r}")
    """Near-real-time quote stream (~15-min-delayed Yahoo data, 60s poll) — never "live"."""
    params = info.context.get("connection_params") or {}
    token = (params.get("authToken") or "").removeprefix("Bearer ").strip()
    _validate_ws_token(token)   # decode_token + type=="access" + is_token_blacklisted → raise GraphQLError("Forbidden" on fail (documented graphql-ws connection_init auth pattern — browser WS can't set headers)

    subscribe_symbol(ticker)
    channel = f"quote:stream:{ticker}"
    try:
        redis = await get_redis(); pubsub = redis.pubsub(); await pubsub.subscribe(channel)  # subscribe FIRST — a tick published between the replay read and subscribe would otherwise be missed
        yield _to_quote(await _fetch_with_timeout(ticker))   # last-value replay (fetch-if-miss;cache+setex → doubles as the replay store)
        async for message in pubsub.listen():
            if message.get("type") == "message":
                yield _to_quote(json.loads(message["data"]))
    finally:
        try: await pubsub.unsubscribe(channel); await pubsub.aclose()
        except Exception: logger.warning("ws_pubsub_close_failed", symbol=ticker)
        unsubscribe_symbol(ticker)
```

- `_validate_ws_token` (module-private in schema.py): reuse `src.auth.utils.decode_token` + `payload.type == "access"` + `await is_token_blacklisted(payload.jti)` (the same primitives as `get_current_user`;no DB user fetch — market data is not user-scoped;document this). Raise `GraphQLError("Forbidden")` on any failure. WS auth happens at `connection_init` only — no mid-stream re-auth;on reconnect, clients must present a fresh access token (RN: `apiService.ensureValidAccessToken()` re-fetches. Add `import re` + `from src.graphql.streaming import subscribe_symbol, unsubscribe_symbol, _fetch_with_timeout` to schema.py.
- `_to_quote(dict) -> Quote` (float-coerce money, ISO datetimes..
- `strawberry.Schema(query=Query, subscription=Subscription)` — rewire schema construction in `router.py` import.

### 4.3 Lifespan wiring — `backend/src/main.py`

- Inside the post-pool `try` block (after `agent_service.initialize()`): `from src.graphql.streaming import start_quote_poller; await start_quote_poller(); logger.info("quote_poller_started")`.
- In `finally` (before `await close_pool()`): `from src.graphql.streaming import stop_quote_poller; await stop_quote_poller()` (stop BEFORE closing the DB/Redis pools — poller uses both). Wrap in try/except (shutdown must never throw past close_pool).

### 4.4 Tests — new `backend/tests/test_graphql_subscriptions.py`

- **Replay:** call the subscription resolver directly with `info` = SimpleNamespace(context={"connection_params": {"authToken": <valid token via auth_headers fixture>}});patch `src.graphql.schema.get_quote` → canned quote;`anext()` → first yield == canned quote (replay;then close (resolver cleanup runs. Assert subscribe-before-replay: fake pubsub records `subscribe()`;it must precede the first yield (no tick can fall into the gap between replay-read and subscribe).).
- **WS auth:** invalid/absent token → resolver raises `GraphQLError` (no yield.

- **Tick delivery:** patch `get_redis` → fake redis whose `pubsub()` returns a fake with `listen()` async-generating one `{"type": "message", "data": json.dumps(quote)}` → second yield == parsed quote.
- **Unsubscribe refcount:** `subscribe_symbol("AAPL")` twice,`unsubscribe_symbol` once → still in registry (count 1);second unsubscribe → removed. Assert `_symbol_subscribers`.
- **Poller tick:** seed registry with 2 symbols;;patch `src.graphql.streaming.get_quote` (side_effects: one raises, one returns);patch `get_redis` → fake `publish` recorder;`await _poller_tick()`;assert: failing symbol skipped (no publish, successful published once to `quote:stream:{SYM}`;and per-tick cost = 1 get_quote per symbol (parallel gather;slow-symbol case: one `get_quote` sleeps 0.1s with `POLL_FETCH_TIMEOUT_SECONDS` patched to 0.01 → skipped (no publish, other symbol still published..
- **Covered (automated + manual):** full WS transport — frontend `subscriptionClient.test.ts` + `quoteMerge.test.ts` cover the client+merge units;;full transport e2e = REQUIRED Phase 6 manual smoke (`wscat`/agent-browser with `connection_init.authToken`;assert replay + tick + disconnect drains registry;RN demo = PortfolioDetail screen — Phase 5+6). — httpx `ASGITransport` has no WS;;covered manually in Phase 6 (`wscat`/agent-browser with `connection_init.authToken`;assert replay + tick + disconnect drains registry).
- **Verification:** `docker compose run --rm pytest tests/test_graphql_subscriptions.py -q`;then `make test`.
- **Acceptance:** replay-before-stream, auth rejection, tick delivery, refcounted unsubscribe stops polling (registry drained at 0, poller tick honors 60s cadence (loop sleep tested by inspection;`_tick` unit-tested, single-process ceiling documented.

---

## Phase 5: Frontend Codegen + Demo Screen Conversion

### 5.1 Commit `schema.graphql` (repo root)

- Full SDL mirror of the backend schema (Query + Subscription + all types + enums). Generated by `print(schema.as_str())` during Phase 3/4 (see Phase 6 diff check);commit it. Codegen never introspects a live server(CI-stable.. Sync rule: any schema.py change → regenerate + recommit both.

### 5.2 `frontend/src/graphql/client.ts` (new, ~40 lines)

```ts
export async function graphqlRequest<TData, TVars = Record<string, unknown>>(
  query: string, variables?: TVars,
): Promise<TData> {
  const token = await apiService.ensureValidAccessToken();   // reuse JWT refresh+SecureStore plumbing (api.ts
  const res = await fetch(`${API_BASE_URL}/graphql`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ query, variables }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body?.errors?.[0]?.message ?? body?.detail ?? 'GraphQL request failed');
  if (body.errors?.length) throw new ApiError(400, body.errors.map((e) => e.message).join('; '));
  return body.data as TData;
}
```

(`API_BASE_URL`/`ApiError` exported from `frontend/src/services/api.ts`;single POST — token pre-freshened, no retry needed.)

### 5.3 `frontend/src/graphql/portfolioDetail.graphql` + `marketQuote.subscription.graphql` (new documents)

```graphql
query PortfolioDetail($id: ID!) {
  portfolio(id: $id) {
    id
    name
    performance {
      portfolio_name
      total_market_value
      total_unrealised_pl
      total_unrealised_pl_pct
      day_change
      day_change_pct
      twr
      twr_start_date
      twr_end_date
      free_cash_balance
      data_quality
      calculated_at
      holdings {
        ticker
        shares
        average_cost_basis
        current_price
        market_value
        unrealised_pl
        unrealised_pl_pct
        day_change
        day_change_pct
        portfolio_weight_pct
      }
    }
  }
}
```

```graphql
subscription MarketQuote($ticker: String!) {
  market_quote(ticker: $ticker) {
    ticker
    price
    change
    change_pct
    previous_close
    timestamp
  }
}
```

(Field selection is the point: only the fields PortfolioDetailScreen renders are requested.)

### 5.4 Convert `frontend/src/screens/portfolio/PortfolioDetailScreen.tsx` (demo: 1 REST poll →  1 GraphQL query + 1 typed quote stream)

- Replace the single `getPerformance(portfolioId)` call **and the 30s `setInterval` poll** (lines ~110-120) with TWO consumers:
  1. **One typed query** — new `portfolioDetail.graphql` doc (`PortfolioDetail($id: ID!)` — see §5.3): `portfolio(id: $id) { id, name, performance { portfolio_name, total_market_value, total_unrealised_pl, total_unrealised_pl_pct, day_change, day_change_pct, twr, twr_start_date, twr_end_date, free_cash_balance, data_quality, calculated_at, holdings { ticker, shares, average_cost_basis, current_price, market_value, unrealised_pl, unrealised_pl_pct, day_change, day_change_pct, portfolio_weight_pct } } }` — field selection = exactly what the screen renders;replace `portfolioService.getPerformance(portfolioId)` with `graphqlRequest<PortfolioDetailQuery>(PORTFOLIO_DETAIL_QUERY, { id: portfolioId })` → `setPerformance(data.portfolio)` (state shape 1:1 `PortfolioPerformance` — render JSX untouched).
  2. **Live quote stream replaces the blind poll** — new `marketQuote.subscription.graphql` doc (`MarketQuote($ticker: String!)`) + `subscriptionClient.ts` + `quoteMerge.ts` + `useLiveQuotes` hook (see §5.4.1-§5.4.3): subscribe each active holding ticker on mount/portfolio-change → `applyQuoteToPerformance(performance, quote)` → `setPerformance`;unmount/portfolio-change → cleanup all (backend refcount registry drains automatically — no backend change). **Delete the `setInterval` block** — no `setInterval` remains on the screen (DoD asserts it).
- **REST stays** the command/write facade + every other screen (hybrid story: read facade + quote stream are tools for this screen, not a migration mandate).
- Generated types map 1:1 to `PortfolioPerformance` (snake_case preserved — no client churn)..

### 5.4.1 `frontend/src/graphql/subscriptionClient.ts` (new, ~45 lines, singleton)

```ts
import { createClient, type Client } from 'graphql-ws';
import { API_BASE_URL } from '../services/api';
import { apiService } from '../services/api';

const wsUrl = (base: string) => base.replace(/^http/, 'ws') + '/graphql';

let sharedClient: Client | null = null;

export function getSubscriptionClient(): Client {
  if (!sharedClient) {
    sharedClient = createClient({
      url: wsUrl(API_BASE_URL),
      connectionParams: async () => {
        const token = await apiService.ensureValidAccessToken();
        return token ? { authToken: `Bearer ${token}` } : {};
      },
      retryAttempts: 5,
    });
  }
  return sharedClient;
}

export function subscribeMarketQuote(
  ticker: string,
  onNext: (quote: MarketQuotePayload) => void,
  onError?: (err: unknown) => void,
): () => void {
  const client = getSubscriptionClient();
  const unsubscribe = client.subscribe(
    { query: MARKET_QUOTE_SUBSCRIPTION, variables: { ticker } },
    { next: onNext, error: onError ?? (() => {}), complete: () => {} },
  );
  // NOTE: do NOT dispose the shared client per subscription — graphql-ws multiplexes
  // N subscriptions over ONE socket. Dispose only on app teardown / logout.
  return () => { unsubscribe(); };
}
```

(graphql-ws multiplexes N tickers over ONE shared socket + reconnects natively; fresh token via `connectionParams` on every (re)connect. Singleton avoids the per-call `createClient` socket leak.)

### 5.5 Codegen + tests

- `npm run graphql:codegen` → commits `frontend/src/graphql/generated.ts` (types + `PortfolioDetailQuery` + `MarketQuoteSubscription`). Commit it (CI-stable alongside schema.graphql).
- **New tests:** `frontend/src/graphql/client.test.ts` (mock fetch + SecureStore; POST URL/body/Bearer; errors→ApiError; non-OK→ApiError(status)) + **`frontend/src/graphql/subscriptionClient.test.ts`** (jest.mock `graphql-ws` — `createClient` returns fake: assert singleton reused across two subscribes, `subscribe` called with the doc + `{ ticker }`; `next` → callback invoked; cleanup → `unsubscribe()` called, `dispose` NOT called per-subscription) + **`frontend/src/graphql/quoteMerge.test.ts`** (pure recompute vs hand-computed: price up/down, unknown ticker ignored, null/0 price no-op, portfolio-level sums + weights recomputed). Screen-level asserts skipped (no RN component-test infra — pre-existing gap).
- **Verification:** `npm run graphql:codegen && npm run typecheck && npm test`.
- **Acceptance:** PortfolioDetailScreen renders from ONE query + live ticks replace the 30s poll (network tab: 1 POST /graphql on focus + WS frames only — no REST polling while focused; typecheck clean, jest green.

### 5.4.2 `frontend/src/graphql/quoteMerge.ts` (new, pure — per CONTEXT.md formulas)

```ts
export function applyQuoteToPerformance(
  performance: PortfolioPerformance,
  quote: { ticker: string; price?: number | null; previous_close?: number | null },
): PortfolioPerformance {
  if (quote.price == null || quote.price === 0) return performance; // null/0 price -> no-op
  const holdings = performance.holdings.map((h) => {
    if (h.ticker !== quote.ticker) return h;
    const market_value = h.shares * quote.price!;
    const cost_basis = h.shares * h.average_cost_basis;
    const unrealised_pl = market_value - cost_basis;
    const unrealised_pl_pct = cost_basis ? (unrealised_pl / cost_basis) * 100 : null;
    // HoldingPerformance has no previous_close — prefer quote.previous_close,
    // fallback to implied prev from last day_change, else current_price (pct -> null-safe).
    const prevClose = quote.previous_close
      ?? (h.day_change != null && h.current_price != null
        ? h.current_price - h.day_change / Math.max(h.shares, 1)
        : h.current_price ?? quote.price!);
    const day_change = h.shares * (quote.price! - prevClose);
    const day_change_pct = prevClose ? ((quote.price! - prevClose) / prevClose) * 100 : null;
    return { ...h, current_price: quote.price!, market_value, unrealised_pl, unrealised_pl_pct, day_change, day_change_pct };
  });
  // Portfolio-level: recompute ALL sums + weights (cheap, N small).
  const total_market_value = holdings.reduce((s, h) => s + (h.market_value ?? 0), 0);
  const total_unrealised_pl = holdings.reduce((s, h) => s + (h.unrealised_pl ?? 0), 0);
  const total_cost_basis = holdings.reduce((s, h) => s + h.shares * h.average_cost_basis, 0);
  const total_unrealised_pl_pct = total_cost_basis ? (total_unrealised_pl / total_cost_basis) * 100 : null;
  const day_change = holdings.reduce((s, h) => s + (h.day_change ?? 0), 0);
  // Day % = day_change / prev-day portfolio value (not cost basis).
  const prev_day_value = total_market_value - day_change;
  const day_change_pct = prev_day_value ? (day_change / prev_day_value) * 100 : null;
  const weighted = holdings.map((h) => ({
    ...h,
    portfolio_weight_pct: total_market_value ? ((h.market_value ?? 0) / total_market_value) * 100 : null,
  }));
  return { ...performance, total_market_value, total_unrealised_pl, total_unrealised_pl_pct, day_change, day_change_pct, holdings: weighted };
}
```

(per CONTEXT.md: Market Value = shares x price; Unrealised = market_value - cost_basis; Day Change = shares x (price - prev_close); Day % = (price - prev_close)/prev_close x 100; Weight = market_value/total x 100. `calculated_at`/`data_quality` stay server-authored. `ponytail:` derived values = live overlay, approximate until next full fetch reconciles; 60s cadence bounds divergence.)

### 5.4.3 `useLiveQuotes` hook (in-screen, ~20 lines — stable ticker-key dep)

```ts
const tickerKey = useMemo(
  () => (performance?.holdings ?? []).filter((h) => h.shares > 0).map((h) => h.ticker).sort().join('|'),
  [performance?.holdings],
);
useEffect(() => {
  if (!tickerKey) return;
  const unsubs = tickerKey.split('|').map((t) =>
    subscribeMarketQuote(t, (quote) => {
      setPerformance((prev) => (prev ? applyQuoteToPerformance(prev, quote) : prev));
    }),
  );
  return () => unsubs.forEach((u) => u());
}, [portfolioId, tickerKey]);
```

(Functional `setPerformance` avoids stale closures; dep is the stable sorted ticker string — NOT the `performance` object — so ticks don't resubscribe every render. Freshness line switches to latest tick `timestamp` (fallback `calculated_at`); pull-to-refresh still full refetch (server reconcile).)

---

## Phase 6: Docs + Verification Sweep

### 6.1 README section — add "Why GraphQL + REST here?" (per ADR 010 framing)

- One typed read graph for the RN app (schema committed, codegen types, introspection available to future authenticated consumers); REST = command facade (writes/OCR/uploads unchanged). Near-real-time caveat verbatim: Yahoo data is ~15-min delayed, polled every 60s — **never "live"**. CV bullet (pinned):
  > Retrofitted a read-only GraphQL layer onto a 40+ endpoint FastAPI REST API: schema-first Strawberry design; batch dataloaders eliminating N+1; JWT resolver-level authz; graphql-codegen typed RN client. PortfolioDetail reads one typed query + a quote stream replacing a 30s blind poll (graphql-ws over RN WebSocket; one shared 60s poller + Redis pub/sub feeds N viewers; ~15-min-delayed data framed as near-real-time).
  Reference `docs/CONTEXT.md` + `docs/adr/010-graphql-read-facade.md` (already written; no re-plan).
- Add a "Schema sync" note (schema.graphql must be regenerated + committed on any `src/graphql/schema.py` change.

### 6.2 Final verification sweep (all commands exact

- Backend lint: `cd backend && .venv/bin/ruff check src tests` (fallback `uv run ruff check src tests`;pyproject line-length 100).
- Backend full suite: `make test` (=`docker compose run --rm pytest`;services postgres/postgres_test/redis auto-required.. Targeted (fast loop): `docker compose run --rm pytest tests/test_graphql_queries.py tests/test_graphql_subscriptions.py tests/test_quote_cache.py tests/test_market.py tests/test_performance.py tests/test_portfolios.py -q`.
- Schema drift check (ad hoc: `docker compose exec backend python -c "from src.graphql.schema import schema; print(schema.as_str())" > /tmp/schema.graphql && diff -u schema.graphql /tmp/schema.graphql` → empty..
- Frontend: `npm run graphql:codegen && npm run typecheck && npm test`.
- Manual WS smoke (**required — the demo**): (a) backend (`wscat`/agent-browser): connect `ws://localhost:8000/graphql`, `connection_init` `{"authToken": "<access token>"}`, `subscription market_quote(ticker: "AAPL")` → immediate last-value replay, then one tick within ~60s;second client same symbol keeps polling after first disconnects(refcount;disconnect last client → registry drained;unauthenticated → rejected (`ConnectionRejectionError`).(b) **RN app (the headline):** `expo start` → open PortfolioDetail → network tab shows ONE `POST /graphql` on focus + WS frames only (no REST polling while focused);prices tick ~60s and the freshness line updates from tick timestamps;pull-to-refresh still does a full refetch.
- Docs: README section committed;CONTEXT/ADR untouched.

### 6.3 Definition-of-Done checklist (all must pass

- [ ] `ruff` clean (backend;no dead code introduced).
- [ ] `make test` green (full backend suite — extraction behavior-neutrality proven by pre-existing suites).
- [ ] New suites green: test_quote_cache, test_graphql_queries, test_graphql_subscriptions..
- [ ] `npm run typecheck` + `npm test` green..
- [ ] PortfolioDetail renders from ONE GraphQL query + live ticks replace the 30s poll (no `setInterval` remains;WS wrapper + quote-merge units green..
- [ ] Schema drift diff empty (schema.graphql in sync).
- [ ] README "Why GraphQL + REST here?" committed (near-real-time caveat present;no "live" claims..
- [ ] Zero changes to: MCP server/agent tools/write/OCR/upload REST paths (git diff scoped to the listed files..
- [ ] Poller stops cleanly on shutdown (lifespan finally;no leaked tasks;;no unhandled exceptions..

## Task Dependency Graph (text)

```
Phase 0 (dep pin, schema.graphql, codegen.yml, verifications)
   ├─▶ Phase 1 (shared read layer)          (needs strawberry? no — pure move; but suites run via pyproject → install first)
   │     ├─▶ Phase 2 (quote cache)            (edits fetch_live_quotes in queries.py → after 1)
   │     └─▶ Phase 3 (GraphQL schema/resolvers)  (imports queries + get_quote → after 1 + 2)
   │                └─▶ Phase 4 (subscription+poller) (extends schema.py + uses get_quote → after 3 + 2)
   │                           └─▶ Phase 5 (frontend codegen+demo)  (needs schema.graphql for types (parallelizable with 3-4) AND Phase 4 backend for the WS smoke; backend runtime only for manual testing)
   └─▶ Phase 6 (docs+verification sweep)   (last; needs everything)
```

**Parallelization:** Phase 1 alone first (biggest test-safety payoff); then Phase 2 + 3 sequential (same files); Phase 4 after 3; Phase 5 codegen/types can start the moment `schema.graphql` lands (parallel with 3-4) but the live-demo smoke requires Phase 4 WS backend.

## Risks & Mitigations

- **Strawberry `context_getter` Depends semantics uncertainty** (auth 401 mechanics): Phase 0 source-inspection gates the choice (Mechanism A vs B;;B includes an ASGI middleware fallback that guarantees REST-parity 401/403. Mitigation documented in §0.1/§3.3..
- **slowapi has no WebSocket support** (verified in upstream README): rate limit applies to HTTP only;WS handshake not limited — code ceiling comment + revisit if abuse appears..
- **Strawberry version drift**: floor-pin `strawberry-graphql[fastapi]>=0.327.0`;;Phase 0 verifies the extra name and `GraphQLRouter` signature against installed version (pip install output + fastapi.py read..
- **REST behavior churn from extraction/cache**: extracted bodies moved verbatim (same SQL/exceptions/models;;quote path gains only a cache layer (TTL 30→60 — the glossary-corrected value;test updated explicitly. Full pre-existing suites = regression net..
- **N+1 on compute (not just DB reads):** `Query.portfolios` reuses `get_bulk_portfolio_performance` (one price_map/one live_quotes/one per-pid compute;unit-tested batch-once assertions. Explicit `startDate`/`endDate` args bypass the batch and compute single-shot (correct-by-construction..
- **Redis downtime**: `get_quote` + poller degrade gracefully (log + fall through;poll tick skips failed symbols — no crash, no dead-letter backlog..
- **Poll delay vs cache TTL**: both 60s → each tick ≈1 yfinance fetch per symbol per minute (bounded;near-real-time framing honest (15-min-delayed Yahoo data..
- **Single-process poller**: in-process refcount registry with code ceiling comment (multi-replica → Redis-backed registry (out of scope;single `docker compose` backend today..
- **schema.graphql drift**: committed file + Phase 6 introspection `diff` check + README sync rule.
- **Preload over-fetch (accepted):** list query caches children even if unrequested — 3 batched reads + 1 batched compute per list query regardless of selection. Fine at ≤small-N;upgrade (deferred: AST-gated conditional preload or a scheduler-verified hand-rolled dataloader.
.
- **Explicit dates on list queries (accepted:** list + explicit `startDate`/`endDate` = N full TWR computes — document in README: deep per-portfolio analytics via `portfolio(id)`.
- **CI test pickup:** confirm the repo's existing backend pytest + frontend jest workflows auto-include the new test files (no workflow change expected;if missing, that's a pre-existing gap, out of scope..
- **Frontend client auth**: reuses `apiService.ensureValidAccessToken()` (token refresh dedup + SecureStore unchanged;;no duplicate token logic..

## HARD BOUNDARIES

- **Read-only facade only.** No mutations in GraphQL — no Strawberry `@strawberry.mutation` anywhere;writes/OCR/uploads stay exclusively REST (and are untouched: no edits to `src/receipts/`, `src/agent/`, `src/mcp/`, upload/OCR REST paths..
- **MCP server / agent untouched.** No MCP tool over GraphQL, no agent tool changes, no introspection-for-agent work..
- **No new ORM.** All DB access via asyncpg through the extracted query modules (`async with connection_ctx() as conn:` house pattern preserved verbatim..
- **Single-process assumption.** In-process refcount symbol registry + code ceiling comments (Redis-backed registry only if multi-replica is ever introduced..
- **No per-client backpressure/queues** at this scale (documented ceiling;add per-client queues if client count grows..
- **No changes to docker-compose services/migrations/schema.** Zero DB migrations;zero new services (poller runs inside the existing backend process, mounted via lifespan..
- **Frontend consumes the quote subscription on PortfolioDetail only** — graphql-ws over RN WebSocket;the single WS consumer in v1 (backend subscription ships per ADR 010;other screens stay REST).
- **`get_quote` is the single quote path** for REST quote endpoint, performance live quotes, query marketQuote, and the poller — no parallel yfinance quote paths introduced..

---

## Compatibility: what this plan does NOT break

Verified against current consumers (Detail = single `portfolioService.getPerformance(portfolioId)` + 30s silent `setInterval`; List = bulk endpoint; agent/MCP = REST tools):

- **Agent (`backend/src/agent/tools.py`, 16 tools) + MCP server:** untouched. No tool changes, no GraphQL-over-MCP, no prompt changes. Agent keeps calling REST performance/summary/holdings helpers. HARD BOUNDARY enforced by git-diff scope check in §6.3.
- **PortfolioDetailScreen:** the ONE converted screen. REST `getPerformance` stays available as fallback; PR deletes its `setInterval` only after query + WS stream render parity is proven. Pull-to-refresh still does a full refetch (server reconcile). No other screen touched.
- **PortfolioListScreen, Summary, Dashboards, Sector/Benchmark/Diversification:** stay on existing REST (`getBulkPerformance`, summary, benchmark comparison). Shared-layer extraction is verbatim (same SQL, same Pydantic models, same 404/400 messages) so their JSON is byte-identical. Quote TTL 30s→60s is the only behavior delta (glossary-normative bug fix) — bounded staleness, no shape change.
- **Backend REST:** routes keep paths, auth (`Depends(get_current_user)`), rate limits, and response models. `fetch_live_quotes` gains only a cache layer via `get_quote`. Rollback = revert GraphQL mount + keep queries.py (REST works through the shared layer either way).
- **Frontend (other screens) + API client:** `apiService.ensureValidAccessToken()` reused, no duplicate token logic. `graphqlRequest` is additive. No navigation/prop changes.

---

## Success Criteria

- [ ] `GET /market/quote/{ticker}` + portfolio performance behave byte-identically post-extraction (pre-existing suites green;TTL now 60s per glossary..
- [ ] `POST /graphql` serves authenticated, user-scoped reads (401 without token;portfolio(id) → null for foreign ids;children scoped by portfolio_id, no re-verify;list query = 3 batched DB reads + 1 batched performance compute for N portfolios — proven by batch-once assertions..
- [ ] `market_quote(ticker)` subscription: auth via `connection_init.authToken`;immediate last-value replay;60s ticks via Redis pub/sub;refcounted registry drains at 0;near-real-time caveat in code + README..
- [ ] PortfolioDetailScreen renders from ONE GraphQL query + live ticks replace the 30s blind poll (codegen types from committed schema.graphql;network tab: one POST /graphql + WS frames while focused;no REST polling;typecheck + jest green..
- [ ] README "Why GraphQL + REST here?" documents the split + caveat;CONTEXT.md + ADR 010 referenced, not re-planned..
- [ ] Full Definition-of-Done checklist (§6.3) passes;git diff touches only the files enumerated in this plan..
