# StockLens — Full Code Review (16 Nov 2026)

Review of `HEAD 481d94d` (clean working tree). Five independent read-only review passes:
backend core (API/db/auth/graphql/mcp), backend domain services, ML + Airflow, frontend
(Expo/RN), and infrastructure/CI/dependencies.

**Status:** most findings are fixed; see `docs/REMEDIATION-LOG.md` for the batch-by-batch record and the deliberately deferred items. This file remains the findings register.

How to read a finding:

- **Severity** — CRITICAL = data loss, security breach, or a feature that is completely
  broken in production. HIGH = silently wrong numbers, security weakness, or a feature
  that fails under realistic use. MEDIUM = correctness/perf/maintainability with a
  workaround. LOW = dead code, drift, and latent risk.
- **Verified** — `V` = re-read by the consolidating reviewer at the cited line.
  `S` = source-read by the area reviewer with an exact citation, not re-verified.
- Every finding cites `path:line`. Fixes are one line by design; they are instructions,
  not patches.

---

## 0. Executive summary — fix these first

| #   | Finding                                                                                                                                                                                                    | Why it is first                                                                                                                                                                                           |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Live credentials committed**: `terraform/tfplan` contains `tfstate` with RDS passwords + JWT secrets; `app.json` carries an OCR.space key; git history has a Firebase key, Alpha Vantage key, and `.env` | Already public. **Rotate first** — rotation is the fix. Repo-side containment is done; history purge is optional and does not affect the contributions graph. See `docs/SECURITY-INCIDENT-2026-11-16.md`. |
| 2   | **No TLS in the deployed path** (`INF-H3`)                                                                                                                                                                 | Every password, JWT, portfolio and receipt crosses the internet in cleartext.                                                                                                                             |
| 3   | **GBp/pence collapse** (`BE-D2`)                                                                                                                                                                           | Every LSE holding, weight, P&L and HHI is wrong by exactly 100× and the wrong rate is persisted.                                                                                                          |
| 4   | **Benchmark endpoint always 500s** (`BE-D1`)                                                                                                                                                               | `dates[i+1]` IndexError on every request with ≥1 trading day.                                                                                                                                             |
| 5   | **OHLCV returns the oldest N rows** (`BE-D3`)                                                                                                                                                              | Prediction runs on ~2006–2014 data; 10Y/20Y projections are computed from truncated history.                                                                                                              |
| 6   | **ML Docker image cannot start** (`ML-C3`)                                                                                                                                                                 | Python 3.14 venv copied into a Python 3.10 CUDA runtime → dangling interpreter.                                                                                                                           |
| 7   | **Weekly drift job cannot import** (`ML-C1`)                                                                                                                                                               | `drift.*` instead of `src.drift.*`; pool never initialised; missing `JWT_SECRET_KEY`. Drift has never run.                                                                                                |
| 8   | **Ingest ignores `TRAINING_TICKERS=ALL`** (`ML-C2`)                                                                                                                                                        | Weekly job refreshes only SPY; models train on frozen data.                                                                                                                                               |
| 9   | **Airflow deletes the backend's Alembic head on every boot** (`INF-C2`)                                                                                                                                    | Silent schema corruption on the next backend deploy.                                                                                                                                                      |
| 10  | **Frontend money/percent contract bugs** (`FE-C2..C4`, `FE-H6`, `FE-H7`)                                                                                                                                   | Double-counted receipts, trade at another ticker's price, native-currency prices shown as GBP, TWR/benchmark 100× too small.                                                                              |

---

## 1. Severity index

| Area                       |   CRIT |   HIGH |     MED |    LOW |   Total |
| -------------------------- | -----: | -----: | ------: | -----: | ------: |
| Backend core               |      1 |      6 |       8 |     10 |      25 |
| Backend domain             |      2 |     13 |      21 |     12 |      48 |
| ML / Airflow / SageMaker   |      3 |      6 |      16 |     16 |      41 |
| Frontend                   |      4 |     14 |      29 |     10 |      57 |
| Infrastructure / CI / deps |      3 |     10 |      27 |     12 |      52 |
| **Total**                  | **13** | **49** | **101** | **60** | **223** |

Cross-area duplicates are listed once and cross-referenced (OCR key, ML image, OHLCV
truncation, TWR formatting, `.env` handling).

---

# 2. Backend core — API, database, auth, GraphQL, MCP

Files: `backend/src/{main,config,limiter,locks,type_aliases}.py`,
`backend/src/database/*`, `backend/src/auth/*`, `backend/src/cache/redis.py`,
`backend/src/graphql/*`, `backend/src/mcp/*`, `backend/alembic/*`.

### BE-C1 — Rate limiting collapses to one global bucket — CRITICAL — V

`backend/src/limiter.py:28-32`, `backend/Dockerfile:125`
`get_remote_address` returns `request.client.host`, which behind the ALB is the ALB ENI.
Uvicorn's `ProxyHeadersMiddleware` only trusts `FORWARDED_ALLOW_IPS` (default
`127.0.0.1`), which nothing sets. Every client shares one bucket, so 20 requests exhaust
`/auth/login` for the whole service and one noisy user throttles everyone.
**Fix:** set `FORWARDED_ALLOW_IPS` to the VPC/ALB CIDR (do not use slowapi's spoofable
`get_ipaddr`); key authenticated routes on `user_id`.

### BE-C2 — bcrypt runs on the event loop — HIGH — V

`backend/src/auth/router.py:120,172`; `backend/src/mcp/auth.py:721`
`hash_password`/`verify_password` are sync calls at ~100–300 ms each inside `async def`.
With `--workers 1` a handful of concurrent logins freezes every request including
`/health`.
**Fix:** `await asyncio.to_thread(...)`; hash after the duplicate check.

### BE-C3 — User enumeration via bcrypt short-circuit — HIGH — S

`backend/src/auth/router.py:170-176`, `backend/src/mcp/auth.py:712-725`
Unknown email returns in ~1 ms, known email in ~250 ms. Same response body, different
timing, so accounts are enumerable — contradicting the deliberate uniform response on
`/auth/forgot-password` (`router.py:213`).
**Fix:** always run `verify_password` against a module-level dummy hash when the row is
`None`.

### BE-C4 — Startup migrations swallow every `ProgrammingError` — HIGH — V

`backend/src/database/init_db.py:333-336`
SQLAlchemy wraps almost all DDL failures as `ProgrammingError` (duplicate table, undefined
column, failed `SET NOT NULL`), so a genuinely broken migration is logged as a benign
worker race and the app boots on a half-migrated schema. The real two-worker race usually
raises `IntegrityError`, which is _not_ caught.
**Fix:** `pg_advisory_lock` around `upgrade()`; otherwise re-read `alembic_version` and
suppress only when it already equals `head`.

### BE-C5 — `.env` existence guard crashes env-var-only deployments — HIGH — V

`backend/src/config.py:140-146` vs `backend/Dockerfile:110-116`
The image does not contain `.env`; ECS injects `ENVIRONMENT=production` plus Secrets
Manager values. `Path(".env").exists()` is false → `RuntimeError` at import, so uvicorn
can never start even though every required value is present. The error message claims
env vars are supported.
**Fix:** drop the file check; pydantic-settings already fails fast on missing required
fields.

### BE-C6 — `_FIX_SQL` is a divergent second copy of the schema — HIGH — V

`backend/src/database/init_db.py:34-284,309-314`
A "repaired" DB is stamped `0010` but built from hand-written DDL. It already lacks
`chk_transactions_amount` from `0001` and adds `DEFAULT 0` where `0008` deliberately
requires explicit values. Two DBs at the same revision have different constraints and no
later migration reconciles them.
**Fix:** replace with `alembic stamp <base> && upgrade head`, or add a `0012` that
re-asserts the CHECK and drops the defaults; assert it in `test_alembic_migrations.py`.

### BE-C7 — Connection pool has no timeout — HIGH — S

`backend/src/database/connection.py:37-45`
`command_timeout=None`, no timeout on `pool.acquire()`. Ten stuck queries starve the
`max_size=10` pool forever while `/health` (no DB) keeps the ALB happy.
**Fix:** `command_timeout=10`, `asyncio.timeout` around acquire, 503 on timeout, and make
`/health` probe the pool.

### BE-M8 — GraphQL-over-WebSocket is anonymous and unmetered — MEDIUM — V

`backend/src/graphql/router.py:35-46`; `backend/src/graphql/schema.py:425-434`
The WS branch returns `user_id: None` and skips `_limited`. `graphql-transport-ws` executes
any operation type over the socket, not just subscriptions — so anonymous, unlimited
queries reach the Yahoo quote path. User-scoped resolvers fail safe (`WHERE user_id = NULL`),
so there is no tenant leak, but it is an open upstream proxy.
**Fix:** reject non-subscription operations on WS (or require `connection_params.authToken`)
and apply a WS-side counter.

### BE-M9 — Malformed JSON-RPC bodies return 500, not `-32600` — MEDIUM — S

`backend/src/mcp/server.py:382-388`
`POST /mcp` with `[1]`, `"x"`, or `params: []` raises `AttributeError: 'int' object has no
attribute 'get'` → 500 with a stack trace in CloudWatch.
**Fix:** `if not isinstance(msg, dict): … -32600`; coerce non-dict `params` to `{}`.

### BE-M10 — MCP tool failures are reported as success — MEDIUM — S

`backend/src/mcp/tools_adapter.py:286-290`; `backend/src/mcp/server.py:256-280`
`invoke_tool` catches every exception and returns `json.dumps({"error": …})`, so
`_handle_tools_call` answers `isError: false`. Clients and LLMs treat a DB outage as valid
data.
**Fix:** re-raise (or return a sentinel) and set `"isError": True` in the existing error
branch.

### BE-M11 — One slow quote kills a subscription at connect time — MEDIUM — S

`backend/src/graphql/schema.py:473`; `backend/src/graphql/streaming.py:35-38`
`_poller_tick` tolerates fetch failures (`return_exceptions=True`); the replay path does
not. A >10 s fetch propagates `TimeoutError` out of the async generator and the client
never gets a tick.
**Fix:** wrap the replay in `try/except` and fall through to `pubsub.listen()`.

### BE-M12 — Refresh tokens accumulate forever — MEDIUM — S

`backend/src/auth/router.py:62-74`; `backend/src/mcp/auth.py:924-932,1005-1013`
One row per login and per rotation; nothing deletes rows; `expires_at` is written but never
read and has no index.
**Fix:** index `expires_at` plus a periodic `DELETE … WHERE expires_at < now() - 1 day`
(or delete on rotation).

### BE-M13 — Unbounded `full_name`/email overflow columns → 500 — MEDIUM — S

`backend/src/auth/schemas.py:73-78`
`EmailStr` caps nothing at 255 and `full_name` has no `max_length`; a long value hits
Postgres `StringDataRightTruncation` on a public endpoint.
**Fix:** `full_name` `max_length=100`, `email` `max_length=255`, strip input.

### BE-M14 — Redis TLS certificate verification disabled — MEDIUM — S

`backend/src/cache/redis.py:24-32`
`rediss://` forces `ssl_cert_reqs=None` → `CERT_NONE` + `check_hostname=False`. Any host on
the VPC path can MITM the JWT blacklist, agent state and MCP auth codes. ElastiCache certs
are issued by Amazon Trust Services and _are_ pinnable; the code comment says otherwise.
**Fix:** ship the Amazon Root CA bundle, `ssl_ca_certs` + `ssl_cert_reqs="required"`.

### BE-M15 — `database/schema.py` is missing columns the DB has — MEDIUM — S

`backend/src/database/schema.py:168-191,245-259,363-383`
Missing `receipts.notes`, `receipts.transaction_date`, `receipts.source`,
`conversations.user_rating`, `conversations.user_rating_comment`, the
`uq_drift_metrics_run_ticker_metric_feature` constraint, and it declares the 0008 GBP
columns nullable. `alembic revision --autogenerate` would **drop five populated columns**.
**Fix:** sync `schema.py`, add an "empty DB upgrade head ⇒ no autogenerate diff" test.

### Backend core — LOW

| ID     | Finding                                                                                                                                                                                    | File:line                                               | Fix                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- | ---------------------------------------------------- |
| BE-L16 | `close_redis()` is never called; pool leaks and rebinds to dead loops in tests                                                                                                             | `cache/redis.py:35-41`; `main.py:141-153`               | call it in the lifespan `finally`                    |
| BE-L17 | `increment_rate_limit`/`get_rate_limit` unused, and `expire` on every call means keys never reset                                                                                          | `cache/redis.py:80-94`                                  | delete, or `expire(..., nx=True)`                    |
| BE-L18 | `create_mcp_app()` dead; it imports `mcp.server.fastmcp.FastMCP`, which the installed mcp 2.3.0 renamed to `MCPServer`. The `# ponytail: pinned <2` comment contradicts `"mcp>=1.12.3,<3"` | `mcp/server.py:447-489`; `pyproject.toml:50`            | delete, or pin `<2`, or port to `MCPServer`          |
| BE-L19 | `alembic.ini` placeholder is not a SQLAlchemy dialect → `upgrade --sql` raises `NoSuchModuleError`                                                                                         | `alembic.ini:2`; `alembic/env.py:31-40`                 | use `settings.DATABASE_URL` for offline mode         |
| BE-L20 | One rate-limit token buys up to 50 tool calls (batch counted as one request)                                                                                                               | `mcp/server.py:63,374-422`                              | `cost=lambda: len(messages)`                         |
| BE-L21 | `initialize` echoes any client `protocolVersion` back, including unsupported ones                                                                                                          | `mcp/server.py:188-196`                                 | validate against `SUPPORTED_VERSIONS`, else `-32022` |
| BE-L22 | Deactivated users keep rotating refresh tokens (only access tokens are rejected)                                                                                                           | `auth/router.py:220-312`; `mcp/auth.py:949-1021`        | join `users.is_active` in the refresh path           |
| BE-L23 | CIMD fetch is a pre-auth SSRF with a documented DNS-rebind TOCTOU                                                                                                                          | `mcp/auth.py:531-562,794-799`                           | connect to the pinned IP with SNI/Host               |
| BE-L24 | 16 JSON schemas rebuilt on every `tools/list`                                                                                                                                              | `mcp/tools_adapter.py:61-99`                            | memoise definitions with `_TOOLS`                    |
| BE-L25 | Conversation list sorts all rows before `LIMIT/OFFSET`; no composite index                                                                                                                 | `agent/repository.py:41-48`; `alembic/versions/0010:47` | `(user_id, updated_at DESC)` index; keyset paging    |

---

# 3. Backend domain services

Files: `market`, `portfolios`, `holdings`, `transactions`, `performance`, `cash_flows`,
`categories`, `prediction`, `drift`, `receipts`, `agent`.

### BE-D1 — Benchmark endpoint always 500s (off-by-one) — CRITICAL — V

`backend/src/performance/queries.py:529-538`

```python
for i, r in enumerate(returns):
    series.append({"date": str(dates[i + 1]), ...})
```

`align_daily_return_series` returns three lists of identical length, so the last iteration
reads `dates[len]` → `IndexError`. `performance/router.py:108-111` re-raises. Benchmark,
alpha and tracking error are dead.
**Fix:** `dates[i]`, plus a test asserting `len(series) == len(common_dates)`.

### BE-D2 — LSE pence prices valued 100× too high — CRITICAL — V

`backend/src/market/fx.py:42,67`

```python
currency = (quote.get("currency") or "GBP").upper()   # "GBp" -> "GBP"
...
if not currency or currency.upper() == "GBP":
    return Decimal("1.0")
```

Yahoo quotes LSE equities in **pence**; `.upper()` erases the distinction, so 300p becomes
£300. The rate is persisted on `holdings`/`transactions`, making the error permanent for
every `.L` ticker in the seed list.
**Fix:** normalise minor units before uppercasing (`GBp→GBP` ×0.01, `ZAc→ZAR`, `ILA→ILS`);
store `fx * divisor`; regression test with `currency="GBp"`.

### BE-D3 — OHLCV returns the **oldest** N rows — HIGH — V

`backend/src/market/repository.py:40-46`
`ORDER BY date ASC LIMIT $n`. Backfill is 20 years (~5 000 rows/ticker), then
`prediction/router.py:77` asks for `limit=2100` and gets 2006–2014. `market/router.py:119`
truncates any wide range at the first 2 000 rows while `total=2000` looks healthy.
`agent/tools.py:761` has the same defect.
**Fix:** `ORDER BY date DESC LIMIT n` + reverse in Python, or reuse the `ROW_NUMBER() …
ORDER BY date DESC` pattern already in `get_ohlcv_batch` (`repository.py:172-176`).

### BE-D4 — Receipt upload buffers the whole file before the size check — HIGH — V

`backend/src/receipts/router.py:157-162`
`await file.read()` then `len(...) > MAX_FILE_SIZE`. A 2 GB multipart body is fully
buffered per concurrent request → OOM.
**Fix:** reject on `Content-Length`, then read in capped chunks and abort at the limit.

### BE-D5 — Unauthenticated endpoints invoke paid Bedrock on every call — HIGH — S

`backend/src/receipts/router.py:69-77,80-104`
`/receipts/health` and `/receipts/cascade/health` have no auth and no limiter, and the
latter runs `llm.ainvoke("Respond with OK")`.
**Fix:** static config check only; the live check belongs in an admin/readiness probe.

### BE-D6 — Drift run leaks every user's holdings and is unbounded — HIGH — V

`backend/src/drift/router.py:68-72`

```python
rows = await conn.fetch("SELECT DISTINCT ticker FROM holdings")   # all users
```

The response echoes `tickers_monitored` and the query has no `user_id` filter. Also 3
metrics × 17 features × N tickers with no admin gate.
**Fix:** `JOIN portfolios p … WHERE p.user_id = $1`; admin-gate the global run.

### BE-D7 — Agent conversation context freezes at the oldest messages — HIGH — V

`backend/src/agent/service.py:133-137,352-356`; `backend/src/agent/repository.py:107-116`
`ORDER BY created_at ASC LIMIT 20` returns the _first_ 20 messages. After ~10 turns the
model never sees its recent replies, while the new question is appended. Same defect on
the history endpoint (`agent/router.py:141`, oldest 50).
**Fix:** `ORDER BY created_at DESC LIMIT n` then reverse, in both places.

### BE-D8 — Empty `portfolio_id` crashes every portfolio tool — HIGH — S

`backend/src/agent/service.py:107` returns `""`; `backend/src/agent/tools.py:72-77` binds it
to `$1::uuid` → asyncpg `DataError`. `graph.py:30-32` explicitly promises graceful
"portfolio not found".
**Fix:** early-return the error object when `not portfolio_id` (or validate once in the
graph node).

### BE-D9 — TWR/tracking-error series is all zeros for buy-and-hold — HIGH — S

`backend/src/performance/queries.py:570-635`
`current` starts `{}` and is only mutated by in-range transactions, so holdings bought
before `start_date` are never seeded — unlike `_compute_twr`
(`calculations.py:444-457`, which does it correctly). Tracking error becomes the
benchmark's own volatility.
**Fix:** seed `current` from transactions dated `<= trading_days[0]`.

### BE-D10 — `_value_at` uses exact-date lookups → holdings vanish on exchange holidays — HIGH — S

`backend/src/performance/queries.py:585-600`
`price_map.get(ticker, {}).get(day_)` returns `None` on a ticker-specific holiday because
`trading_days` is the union calendar. Every non-trading holding is valued at 0, manufacturing
fake −x%/+x% pairs.
**Fix:** use the closest prior price (`_get_closest_price` already does `bisect_right`).

### BE-D11 — FX is fail-open — HIGH — S

`backend/src/transactions/router.py:257-259`; `backend/src/holdings/router.py:163-165`;
`backend/src/market/fx.py:44-46`
A provider outage records `currency='GBP'`, `fx_rate_to_gbp=1`, inflating a USD buy by
~27%; the row is persisted and never corrected, and `fx_unknown_tickers` cannot detect it.
**Fix:** 503 on failure (retryable), or persist `NULL` and treat unknown as unknown.

### BE-D12 — Market value uses the **buy-time** FX rate forever — HIGH — S

`backend/src/performance/calculations.py:59-64`; `backend/src/performance/queries.py:397`
`fx_rate` comes from `holdings.fx_rate_to_gbp`, overwritten on each buy and never refreshed,
so FX P&L is invisible; cost basis is re-derived from `native_avg × last_buy_rate` while the
correct `average_cost_basis_gbp` column sits unused.
**Fix:** value at the current rate for the valuation date; read cost basis from
`average_cost_basis_gbp`.

### BE-D13 — JSONB is double-encoded; drift then calls `.get()` on a string — HIGH — V

`backend/src/database/connection.py:27-36` registers `encoder=json.dumps`, but writers pass
pre-serialised strings: `prediction_logger.py:210-213`, `receipts/router.py:236,372-380`,
`categories/seed.py:355-363`. The stored value is a JSON string and the decoder returns
`str`, so `drift/service.py:133-135` raises `AttributeError: 'str' object has no attribute
'get'` → `POST /drift/run` 500s. The `isinstance(..., str)` re-decode workarounds at
`receipts/router.py:405-406,434-435` and `merchant_map.py:63-72` corroborate it.
**Fix:** pass Python objects to `::jsonb`; delete the `json.dumps` wrappers and re-decodes.

### BE-D14 — Sync torch inference blocks the event loop — HIGH — S

`backend/src/prediction/router.py:93` → `prediction/service.py:159-416`
Pandas feature construction plus `len(ensemble)` LSTM forward passes run synchronously in
the endpoint (again at `agent/tools.py:921`). Hundreds of ms to seconds of CPU on the single
loop thread.
**Fix:** `await asyncio.to_thread(prediction_service.predict, ...)`; same for the sync boto3
`_sagemaker_predict` (`service.py:295-311`).

### BE-D15 — Diversification "top weight" is an arbitrary holding — HIGH — S

`backend/src/agent/tool_endpoints.py:420`
`weights_decimal[0]` comes from a query with **no `ORDER BY`** (`:382-390`), while line 483
reports `values_sorted[0]` and line 457 gates the recommendation on `> 0.4`. The score and
the displayed top holding describe different rows.
**Fix:** `max(weights_decimal)`, use `values_sorted[0]` consistently, `ORDER BY h.ticker`.

### BE-M16 — Drift persistence is N+1 pool round-trips — MEDIUM — S

`backend/src/drift/router.py:131-136`; `drift/repository.py:15-53`
One `INSERT` per metric with its own acquire/release: a 30-ticker run ≈ 1 530 round-trips.
**Fix:** one connection, `executemany` or a multi-row `INSERT`.

### BE-M17 — PSI/JS silently drop out-of-range production values — MEDIUM — S

`backend/src/drift/service.py:54-55,262-264`
`np.histogram(current, bins=reference_percentile_edges)` discards outliers, then proportions
re-normalise over the survivors. A distribution shifted _outside_ the reference range —
exactly the drift you want — reports stable.
**Fix:** extend the first/last edge to the combined min/max before histogramming.

### BE-M18 — Bedrock classification path can never succeed — MEDIUM — S

`backend/src/categories/merchant_map.py:204-222`
Builds the Anthropic Claude `InvokeModel` envelope and parses `content[0].text`, but the
model is `amazon.nova-lite-v1:0` (`config.py:42`), which needs `messages[]`/`inferenceConfig`
and returns `output.message.content[].text`. The `except Exception` hides the
`ValidationException`. The extractor does it correctly via `converse` (`llm_extractor.py:121-136`).
**Fix:** use `client.converse(...)`.

### BE-M19 — Bedrock retry predicate string-sniffs; never retries throttling — MEDIUM — S

`backend/src/receipts/llm_extractor.py:167-180`
`"5" in msg and ("server error" …)` misses `ThrottlingException` (the dominant transient
failure) and retries `ValidationException` three times.
**Fix:** inspect `ClientError.response["Error"]["Code"]` / `HTTPStatusCode >= 500`.

### BE-M20 — yfinance retries permanent 4xx for ~2 minutes — MEDIUM — S

`backend/src/market/provider.py:36-38`
`HTTPError` covers 404/401; `retry(5, wait_exponential(max=60))` then burns ~2 min inside a
request for a bad ticker.
**Fix:** only retry 429 and ≥500.

### BE-M21 — `Ticker.news` parsing uses the pre-1.x schema — MEDIUM — S

`backend/src/agent/tools.py:861-879`; `agent/tool_endpoints.py:257-278`
Reads `title`/`publisher`/`link`/`providerPublishTime`; yfinance ≥1.5 returns
`{"content": {"title", "pubDate", "canonicalUrl", "provider"}}`. Every field is `None` and
the dedupe collapses all articles into one.
**Fix:** `article.get("content", article)` + `pubDate`/`canonicalUrl.url`.

### BE-M22 — `parse_total` can pick cash-tendered/change — MEDIUM — S

`backend/src/receipts/ocr.py:209-214,314-337`
`TOTAL_PATTERNS[3]` takes the last currency line, so a garbled TOTAL label yields
`CASH £20.00`/`CHANGE £11.50`. `parse_line_items` filters `_NON_ITEM_LABEL`; `parse_total`
does not.
**Fix:** skip `cash|change|tendered|tip` lines before the fallback patterns.

### BE-M23 — Four Tesseract passes and four full parse passes per receipt — MEDIUM — S

`backend/src/receipts/ocr.py:184-203,489-503,567-585`
Three PSM runs, then the full parser + 13 RapidFuzz scans per candidate, then a re-parse of
the winner, then a fourth `image_to_data`.
**Fix:** carry confidence from the winning mode and cache the parse per text.

### BE-M24 — `raw_text_hash` stores 16 chars of OCR text (PII) — MEDIUM — S

`backend/src/receipts/router.py:248` — `raw_text[:16]`, frequently the merchant name; not
unique, useless for dedupe. `cache.py:24-26` already has `sha256(...)[:16]`.
**Fix:** use the hash helper.

### BE-M25 — Agent tools bypass the quote cache, no concurrency cap — MEDIUM — S

`backend/src/agent/tools.py:109-124,301-320,435-440,506-518`
Call `provider.fetch_quote` directly and `gather` over all holdings, bypassing
`market/quotes.py` (Redis, 60 s). `performance/queries.fetch_live_quotes` is the correct
bounded implementation (`Semaphore(8)` + 10 s timeout). With >32 holdings the shared default
executor saturates app-wide.
**Fix:** route through the cached, semaphore-bounded helper.

### BE-M26 — Sector endpoints call `Ticker.info` per holding per request — MEDIUM — S

`backend/src/agent/tool_endpoints.py:67-72,306-363,369-444`; duplicated at
`agent/tools.py:236-250`
1–3 s, retried 3×, uncached, no persisted sector. A 20-holding portfolio costs seconds and
four call sites repeat it.
**Fix:** persist `sector` on `instruments` on first resolve, or cache per ticker.

### BE-M27 — Sector/weight/HHI computed at cost basis, not market value — MEDIUM — S

`backend/src/agent/tools.py:216-230,641-661`; `agent/tool_endpoints.py:314-327,395-448`
`value = shares * average_cost_basis_gbp` used as market value and allocation, so exposures
are historical cost weights and disagree with `/portfolio/performance`.
**Fix:** reuse the live-price valuation.

### BE-M28 — `get_lstm_forecast` drops the SPY features the model was trained with — MEDIUM — S

`backend/src/agent/tools.py:921`
No `spy_ohlcv_rows`, so `service.py:224-229` zero-pads 3 of 17 inputs. `/predict/{ticker}`
passes SPY, so agent and REST give different forecasts for the same ticker.
**Fix:** fetch SPY rows or route through the router path.

### BE-M29 — `get_market_ohlcv` can dump 2 000 rows into the model context — MEDIUM — S

`backend/src/agent/tools.py:754-766`
Default `limit=2000`, serialised verbatim — tens of thousands of tokens, cost and truncation
risk.
**Fix:** cap (~250) and/or return an aggregate.

### BE-M30 — Chat message length is unbounded — MEDIUM — S

`backend/src/agent/schemas.py:19` — `message: str`. A 5 MB paste goes into the prompt.
**Fix:** `max_length=8000`.

### BE-M31 — Live quotes override historical valuations — MEDIUM — S

`backend/src/performance/queries.py:402` always passes `live_quotes`;
`calculations.py:246-252` applies them unconditionally. `?end_date=2025-03-31` reports
today's price for that date.
**Fix:** pass live quotes only when `end_date` is absent or ≥ today.

### BE-M32 — Performance never bootstraps OHLCV for its holdings — MEDIUM — S

`backend/src/performance/queries.py:399` reads the DB only, while
`get_benchmark_comparison` (`:463-473`) refreshes and backfills. A new portfolio silently
gets `twr=None`/`data_quality="partial"`.
**Fix:** bounded, batched refresh of holding tickers before computing.

### BE-M33 — Thundering herd + 20-year re-download on cold tickers — MEDIUM — S

`backend/src/market/router.py:39-77`
No per-ticker lock; N concurrent cold requests each download 20 years with up to 5 retries
and upsert 5 000 rows. Also `staleness_days=1` re-fetches every Sunday (Friday's close is
older than the cut-off).
**Fix:** per-ticker lock (or Redis `SET NX`); 2-day tolerance at weekends.

### BE-M34 — Heavy yfinance endpoints are unthrottled — MEDIUM — S

`backend/src/agent/tool_endpoints.py` — none of the 7 endpoints has `@limiter.limit`, while
the rest of the API does. Each fans out blocking `.info` calls.
**Fix:** standard limiter + shared executor cap.

### BE-M35 — Non-UUID `category_id` → 500 — MEDIUM — S

`backend/src/receipts/models.py:55,70` type it `str`; `router.py:486,588` bind `$4::uuid`.
`scan_receipt` already guards manually (`:212-216`).
**Fix:** `Optional[UUID]`.

### BE-M36 — Two different PSI thresholds — MEDIUM — S

`backend/src/drift/evidently_reporter.py:63-68` uses `threshold=0.05`; the API alerts at
`DRIFT_ALERT_PSI_THRESHOLD = 0.25` (`drift/service.py:18`, `config.py:77`). The HTML report
and the JSON verdict disagree routinely.
**Fix:** pass the setting.

### Backend domain — LOW

| ID     | Finding                                                                                                                                                                                                                                                               | File:line                                                                                                                                                                                           | Fix                              |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| BE-L37 | ~90 lines duplicated between nested/flat holding update & delete                                                                                                                                                                                                      | `holdings/router.py:241-316,380-448,319-353,451-481`                                                                                                                                                | extract one helper               |
| BE-L38 | Edit re-derives GBP cost from the stored (frozen) FX rate                                                                                                                                                                                                             | `holdings/router.py:271,421`                                                                                                                                                                        | fix with BE-D12                  |
| BE-L39 | Dead schemas: `BatchQuoteResponse`, `OHLCVParams`, `PerformanceParams`, `BenchmarkParams`, `CategoryCreate`, `CashFlowInDB`, `CascadeDecisionDB`, `ToolCallEvent`, `ToolResultEvent`, `SSEEvent`, `ConversationSummary`, `MessageResponse`, `PredictionErrorResponse` | `market/schemas.py:49,57`; `performance/schemas.py:108,116`; `categories/schemas.py:25`; `cash_flows/schemas.py:32`; `receipts/models.py:172`; `agent/schemas.py:23-62`; `prediction/schemas.py:26` | delete                           |
| BE-L40 | `update_receipt` rewrites `scanned_at` with its current value                                                                                                                                                                                                         | `receipts/router.py:609-611`                                                                                                                                                                        | remove clause                    |
| BE-L41 | `KNOWN_MERCHANTS` duplicated                                                                                                                                                                                                                                          | `receipts/cascade.py:52`; `receipts/merchant_match.py:23`                                                                                                                                           | import one copy                  |
| BE-L42 | Docstring says DeepSeek V3.1; config uses Nova Lite                                                                                                                                                                                                                   | `agent/graph.py:40`; `config.py:84`                                                                                                                                                                 | fix docstring                    |
| BE-L43 | Startup issues `CREATE TABLE`/`CREATE INDEX` and acquires one connection per category                                                                                                                                                                                 | `categories/seed.py:332-346`                                                                                                                                                                        | drop DDL; one `executemany`      |
| BE-L44 | `langchain-core>=0.3.0` floor conflicts with `langgraph>=1.0`/`langchain-aws>=1.6`                                                                                                                                                                                    | `pyproject.toml:24`                                                                                                                                                                                 | raise to 1.x                     |
| BE-L45 | `typing_extensions.Literal` on Python ≥3.12                                                                                                                                                                                                                           | `receipts/models.py:12`                                                                                                                                                                             | `typing.Literal`                 |
| BE-L46 | `list_runs` accepts unbounded `limit`                                                                                                                                                                                                                                 | `drift/router.py:196-203`                                                                                                                                                                           | `Query(ge=1, le=…)`              |
| BE-L47 | `boto3.client("s3")` per call, no region → silent `NoRegionError`                                                                                                                                                                                                     | `drift/utils.py:25,52`                                                                                                                                                                              | module client with `region_name` |
| BE-L48 | Numeric overflow on oversized input → 500 instead of 422                                                                                                                                                                                                              | `holdings/schemas.py`, `transactions/schemas.py`, `cash_flows/schemas.py`                                                                                                                           | bound fields                     |

---

# 4. ML pipeline, Airflow, SageMaker

Files: `backend/ml/*`, `airflow/dags/*`, `airflow/scripts/*`, `backend/scripts/*`,
`backend/sagemaker/*`, `backend/agent_eval/*`.

### ML-C1 — Weekly drift detection cannot import, pool uninitialised, secret missing — CRITICAL — V

`airflow/dags/weekly_retraining.py:206-222,229,241,247`
Three independent breaks:

1. imports `drift.*`; the package is `backend/src/drift` → only `src.drift` is importable
   from `/app`.
2. `_run_drift_detection` uses `connection_ctx()` but nothing calls `init_pool()` (only
   `src/main.py:75` and `agent_eval/run_experiment.py:113` do) → `RuntimeError`.
3. `src/drift/service.py:9` imports `src.config.settings`, which requires `JWT_SECRET_KEY`;
   the Airflow task env does not set it → `ValidationError`.
   `airflow/dags/test_handlers.py:298-321` fakes `drift.*` modules, which is why CI passes.
   **Fix:** `from src.drift…`; `await init_pool()`/`close_pool()`; supply `JWT_SECRET_KEY` or
   decouple drift from `src.config`.

### ML-C2 — `TRAINING_TICKERS=ALL` is not understood by the ingest script — CRITICAL — V

`backend/scripts/seed_ohlcv.py:65-81`; `airflow/dags/weekly_retraining.py:84`;
`airflow/scripts/init_airflow_variables.sh:79`
The sentinel `"ALL"` (`ml/config.py:495-502`) is treated as a literal ticker, so the universe
is `["ALL", "SPY"]`. The bogus symbol fails and is swallowed (`:204-207`); only SPY advances.
The weekly data lifecycle is effectively dead.
**Fix:** special-case `ALL` → `ml.config._ALL_SP500`.

### ML-C3 — ML image copies a 3.14 venv into a 3.10 runtime → cannot start — CRITICAL — V

`backend/ml/Dockerfile:42,66-86`
Builder is `python:3.14-slim`; runtime is `nvidia/cuda:12.4.1-runtime-ubuntu22.04` (Python
3.10). `/app/.venv/bin/python` is a symlink to `/usr/local/bin/python3.14`, which does not
exist in the runtime. The runtime venv created at `:78` is then overwritten at `:86`.
**Fix:** build the venv in the runtime stage (or use a CUDA-enabled Python 3.14 base); never
copy a venv across interpreter versions.

### ML-H1 — `skip_retraining` dead-ends — drift and cleanup never run — HIGH — V

`airflow/dags/weekly_retraining.py:434-436`
`skip_retraining` has no downstream task, yet drift + prediction-log pruning are documented
as unconditional (`:10-18`). With a 14-day guard, roughly every other week produces no drift
metrics and no pruning.
**Fix:** `[train_challenger, skip_retraining] >> run_drift >> cleanup`.

### ML-H2 — Promotion metrics logged after the MLflow run ends — HIGH — S

`backend/ml/pipeline.py:715-716,885-1005`; `mlflow_manager.py:95-102`
`end_run()` in `finally`, then `log_metrics(gate_metrics)` with no active run. MLflow creates
a new implicit run, which is never ended, so the orphan is KILLed later. No promotion is
attributable to its run.
**Fix:** capture `run_id` and log with it, or log inside the run.

### ML-H3 — Paired McNemar gate never runs in production — HIGH — S

`backend/ml/pipeline.py:893-960`
The gate looks for `model.pt` on ECS's ephemeral disk. The champion is only published to
`CHAMPION_S3_URI`; nothing downloads it, so every run falls back to the weaker unpaired gate
(`:962-970`).
**Fix:** download/extract `model.tar.gz` (logic exists in `sagemaker/serve.py:59-97`) before
the gate.

### ML-H4 — Champion alias is a race, and points at a different model than serves — HIGH — S

`backend/ml/mlflow_manager.py:226-242`; `pipeline.py:681-684,702,1011`
`log_model`'s `registered_model_version` is ignored in favour of `max(version)`, which any
concurrent registration can win. Only seed-0 is registered while the ensemble of 5 is
served, so the registry champion is not what was gated or served.
**Fix:** use the returned version; register the ensemble as a single artifact/pyfunc.

### ML-H5 — GPU image installs CPU torch — HIGH — S

`backend/ml/Dockerfile:53-59`; `backend/ml/pyproject.toml:27-32`
`pip install …cu126` lands in system site-packages; `uv sync` creates an isolated venv and
resolves `torch` from the `pytorch-cpu` index. Training runs `+cpu` on a GPU instance, plus
~2.5 GB of dead CUDA download.
**Fix:** point the uv index at `cu126` for the training image; drop the `pip install`.

### ML-H6 — `Variable.get()` at DAG-parse time; `app_name` never seeded — HIGH — S

`airflow/dags/weekly_retraining.py:169-172,358-408`;
`airflow/scripts/init_airflow_variables.sh`
Eight metadata-DB reads at import. `app_name` has no default in the init script or compose,
so the DAG import raises locally and disappears from the UI; one missing variable breaks the
whole file in prod.
**Fix:** read variables inside callables with `default_var`, or seed every key.

### ML-M1 — Phase-2 HPO rebuilds the whole dataset 8× — MEDIUM — S

`backend/ml/hpo.py:166-169,449-456`
Only labels change per `threshold_mult`, yet each iteration re-fetches six years of OHLCV and
recomputes all features. `object.__setattr__` bypasses `frozen=True`, leaving the global
mutated; the sweep (0.3–1.0) can never produce the production default of 2.0.
**Fix:** build once, recompute labels only; pass the threshold as a parameter.

### ML-M2 — Threshold selection compares accuracies over different populations — MEDIUM — S

`backend/ml/hpo.py:482-519`; `evaluate.py:89-96,143-182`
Each candidate defines a different FLAT band, so `val_dir_acc` is measured over a different
subset. The margin sweep has the same property.
**Fix:** select on a fixed-population metric, or log `n_directional` alongside the score.

### ML-M3 — `log_dataset` flattens ~1.4 GB six times — MEDIUM — S

`backend/ml/pipeline.py:525-530`
MLflow 3.x `compute_numpy_digest` does `array.flatten()` to hash the first 10k elements. A
500-ticker train split is ~1.4 GB, allocated six times.
**Fix:** pass a pre-computed digest over a subsample, or log metadata instead of the array.

### ML-M4 — Reference distributions materialise every timestep — MEDIUM — S

`backend/ml/pipeline.py:843-846,1034-1038`; `reference_distributions.py:96-114`
`reshape(-1, 17)` on (N, 30, 17) ≈ 21M rows, plus another full copy for the NaN mask, right
after training — ~3 GB transient.
**Fix:** one row per window (`[:, -1, :]`) or stride-sample; drop the `np.copy`.

### ML-M5 — Class weights cost a full loader pass per seed — MEDIUM — S

`backend/ml/train.py:239-246`; `pipeline.py:539-541`
Five redundant DataLoader epochs, and it advances the RNG before training starts.
**Fix:** compute weights once from the label array already in memory.

### ML-M6 — Unpaired fallback gate treats the champion as a known constant — MEDIUM — S

`backend/ml/promotion_stats.py:193`
`binomial_one_sided_p(..., champion_da)` ignores the champion's sampling error from a
different period → anti-conservative p-values. Since ML-H3 makes this the only production
gate, it can promote a zero-edge challenger.
**Fix:** two-proportion z-test / Fisher exact using both sample sizes, or fail closed.

### ML-M7 — Baseline HGB early-stops on a random split — MEDIUM — S

`backend/ml/baselines.py:78-80`
`early_stopping=True` with the default shuffled 10% validation lets future rows validate
past ones, biasing the baseline that the LSTM is compared against.
**Fix:** `early_stopping=False` or a chronological validation slice.

### ML-M8 — Ensemble publish is not atomic — MEDIUM — S

`backend/ml/mlflow_manager.py:508-541,555-575`
`model.pt` is replaced, then seeds, then stale seeds pruned. A backend starting mid-publish
loads new metadata with mixed weights while `len(seed_paths)` matches; the S3 path can crash
between the tar and individual uploads.
**Fix:** write to a new versioned dir and flip a pointer atomically; upload the tar last (or
serve only the tar).

### ML-M9 — `make train` deploys only `model.pt` — MEDIUM — S

`Makefile:60-63`; `backend/src/prediction/service.py:82-96`
`docker compose cp` copies one file; `load_model`'s no-seeds branch never checks
`_ensemble_size`, contradicting its docstring. The deployed model is seed-0 only.
**Fix:** copy `model_seed*.pt`; check `expected` in the single-file branch.

### ML-M10 — Fetch layer materialises ~750k rows three times — MEDIUM — S

`backend/ml/pipeline.py:96-135`
`fetch` → Record objects → per-ticker lists → tuple list, plus a Python double loop. Largest
memory peak before training.
**Fix:** `copy_from_query`/`read_sql`, or build one structured array from columns.

### ML-M11 — OHLCV upsert is `DO NOTHING`; restated history never updates — MEDIUM — S

`backend/scripts/seed_ohlcv.py:159-164`
Yahoo re-states `adjusted_close` after every split/dividend. Existing rows keep pre-split
adjustments and intraday partial bars, corrupting `log_ret`, labels and `vol_rank`.
**Fix:** `DO UPDATE … WHERE adjusted_close IS DISTINCT FROM EXCLUDED.adjusted_close`; only
ingest dates < today.

### ML-M12 — Ingest reports success when 488/489 tickers fail — MEDIUM — S

`backend/scripts/seed_ohlcv.py:223-225`
Only fails when _all_ tickers fail; one success exits 0 and the DAG trains on stale data.
**Fix:** fail above a failure ratio (e.g. 10%) or when `total == 0`.

### ML-M13 — `load_reference_from_db` crashes on real jsonb — MEDIUM — S

`backend/ml/reference_distributions.py:216-240`
No jsonb codec registered, so `dict(row["metrics"])` on a `str` raises. Latent because only
tests with a fake connection exercise it.
**Fix:** register the codec (`mlflow_manager.py:380-385` does) or `json.loads`.

### ML-M14 — Airflow 3 config keys are in pre-3.0 sections — MEDIUM — S

`airflow/Dockerfile:109`; `airflow/config/airflow.cfg:10-11`
`min_file_process_interval` moved from `[scheduler]` to `[dag_processor]`; the env var and
cfg line are ignored. Matters more here because parse-time `Variable.get` is the slow part.
**Fix:** `AIRFLOW__DAG_PROCESSOR__MIN_FILE_PROCESS_INTERVAL`.

### ML-M15 — Legacy Airflow imports mixed with the 3.x SDK — MEDIUM — S

`airflow/dags/weekly_retraining.py:29-32,57,169-172`; `airflow/dags/test_dag.py:16`
`airflow.models.DAG`, `airflow.operators.*`, `airflow.hooks.base.BaseHook` beside
`airflow.sdk.Variable`.
**Fix:** `airflow.sdk.DAG`, `airflow.providers.standard.operators.*`,
`airflow.sdk.bases.hook.BaseHook`.

### ML-M16 — SageMaker handler is single-threaded — MEDIUM — S

`backend/sagemaker/serve.py:233`
`HTTPServer` serialises requests (HTTP/1.0, no keep-alive) while each holds the GIL for the
full ensemble pass.
**Fix:** `ThreadingHTTPServer` + `protocol_version = "HTTP/1.1"`.

### ML / Airflow — LOW

| ID     | Finding                                                                                                                                                                | File:line                                                                                                                             | Fix                                             |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| ML-L17 | Label docstring says `0.3`/28-36-36; default is 0.5, config 2.0 (~95% FLAT). `compute_label_distribution` has no callers, so label balance is never recorded           | `labeling.py:9-16,37,72-87`; `config.py:519`                                                                                          | correct docstring; log distribution in pipeline |
| ML-L18 | `except Exception` around Sharpe returns `None`, silently degrading every headline metric                                                                              | `evaluate.py:204-206`                                                                                                                 | log traceback or fail the gate                  |
| ML-L19 | Fixed `/tmp` artifact names collide across concurrent runs                                                                                                             | `pipeline.py:669,675,678`; `hpo.py:548,583`                                                                                           | `tempfile.mkdtemp()` per run                    |
| ML-L20 | `_record_in_db` runs after MLflow/disk promotion; a DB failure silently reverts the gate to unpaired                                                                   | `pipeline.py:1009-1020,1083-1099`                                                                                                     | one ordering, recoverable write                 |
| ML-L21 | Tickers with 60–281 rows are dropped with no log                                                                                                                       | `pipeline.py:117-119,303-304`                                                                                                         | warn with ticker + window count                 |
| ML-L22 | Exact McNemar enumerates huge `math.comb` sums in the weekly job                                                                                                       | `promotion_stats.py:44`                                                                                                               | normal approximation / `scipy.stats.binomtest`  |
| ML-L23 | `hash()` is salted per process, so seeded eval prices differ every CI run                                                                                              | `scripts/seed_eval.py:79,85`                                                                                                          | `zlib.crc32` / seeded `Random`                  |
| ML-L24 | `PREDICTION_CACHE_TTL` defined three times; router hardcodes `21600`                                                                                                   | `ml/config.py:638`; `src/config.py:71`; `src/prediction/router.py:32`                                                                 | read the setting                                |
| ML-L25 | Airflow Dockerfile comment says 3.12, both stages are 3.14; requirements floors drift from the image                                                                   | `airflow/Dockerfile:2-3,8,38,75-91`; `airflow/requirements.txt`                                                                       | one pinned source                               |
| ML-L26 | Comment says backend source is not copied; `COPY backend/ /app/` does copy it                                                                                          | `airflow/Dockerfile:102-103,113-114`                                                                                                  | fix comment or copy                             |
| ML-L27 | `_detect_new_champion` branches on a 6-hour recency heuristic into a no-op                                                                                             | `weekly_retraining.py:175-197,419`                                                                                                    | compare model versions or delete                |
| ML-L28 | `datetime.now().strftime("%Y-%m-%d_%Y-%m-%d")` always produces `X_X`                                                                                                   | `weekly_retraining.py:226`                                                                                                            | use real lookback bounds                        |
| ML-L29 | Drift query mixes predictions from two models across a champion change                                                                                                 | `weekly_retraining.py:248-255`                                                                                                        | filter by `model_version`                       |
| ML-L30 | Test docstring says requirements has no asyncpg; it does                                                                                                               | `airflow/dags/test_handlers.py:8-11`                                                                                                  | fix                                             |
| ML-L31 | Dataset delete+create detaches prior LangSmith examples                                                                                                                | `agent_eval/upload_dataset.py:33-34`                                                                                                  | upsert                                          |
| ML-L32 | Dead ML code: `tag_best_run`, `get_ticker_idx`, `compute_label_distribution`, `save_reference`/`load_reference`, individual indicator wrappers, `standardise_features` | `mlflow_manager.py:298-358`; `utils.py:54-64`; `labeling.py:72-87`; `reference_distributions.py:248-286`; `features.py:30-86,207-229` | delete or wire up                               |

**Verified clean in ML:** normalisation is fit on train only; `vol_rank`/`compute_causal_vol_pct`
are trailing; split boundary + embargo are correct; window alignment has no off-by-one;
Sharpe de-overlaps per ticker correctly; MLflow 3.x API usage is current; no removed
numpy-2/pandas-3 APIs; no Airflow 2 leftovers; no XCom size risk; SageMaker input contract is
correct.

---

# 5. Frontend (Expo / React Native)

Files: `frontend/src/{services,hooks,contexts,utils,screens,components,navigation,graphql}`,
`App.tsx`, `index.ts`, `jest.setup.ts`, `app.json`, root `package.json`.

`tsc --noEmit` and ESLint pass — every defect below is invisible to the typechecker because
backend contracts are not typed across the boundary.

### FE-C1 — Live OCR.space API key committed in the app config — CRITICAL — V

`app.json:26` — literal key in `expo.extra`, bundled into every client and readable from the
binary or source. Public repo. (Same credential class as INF-C3.)
**Fix:** revoke/rotate, remove from history, move OCR to the backend (`/receipts/scan` exists).

### FE-C2 — "Enter manually" after a scan creates a second receipt — CRITICAL — S

`frontend/src/hooks/useReceiptCapture.ts:160-185,64-90`;
`frontend/src/screens/ScanScreen.tsx:184-195`
The scan endpoint already inserted a receipt (and returned `result.id`). "Rescan" deletes the
draft; "Enter manually" POSTs a **new** receipt. Home/Summary then count both, inflating
spend and every projection.
**Fix:** update the pending scan's receipt (or delete the draft) instead of creating.

### FE-C3 — Trade can submit one ticker at another ticker's quote — CRITICAL — S

`frontend/src/screens/portfolio/TradeScreen.tsx:112-130,206-207`
`quote` is not cleared when the ticker changes and `canConfirm` never checks
`quote.ticker === ticker`. Changing AAPL→TSLA after a blur posts TSLA with AAPL's price.
`keyboardShouldPersistTaps="handled"` makes the missed blur likely. Out-of-order quote
fetches add a second race.
**Fix:** clear on change, gate on a matching ticker, sequence/abort fetches.

### FE-C4 — Live quote overlay applies native-currency prices as GBP — CRITICAL — S

`frontend/src/screens/portfolio/PortfolioDetailScreen.tsx:150-160`;
`frontend/src/graphql/quoteMerge.ts:18-46`; `frontend/src/graphql/subscriptionClient.ts:17-28`
Performance holdings are GBP-normalised server-side, but the subscription publishes raw
native-currency quotes (and does not request `currency`). A USD holding jumps by the FX rate
on every tick; `applyQuotesToPerformance` re-applies it.
**Fix:** request `currency` and convert to GBP server-side before publishing (preferred), or
reject non-GBP ticks client-side.

### FE-H5 — Launching offline signs the user out — HIGH — V

`frontend/src/services/api.ts:74-99,182-188`; `frontend/src/contexts/AuthContext.tsx:139-149`
A network failure during refresh returns `false`, `api()` raises `ApiAuthError`, `getProfile()`
returns `null`, and `AuthContext` deletes a still-valid 7-day refresh token. The comment at
`AuthContext.tsx:150-156` claims the opposite.
**Fix:** only clear tokens on a definitive 4xx refresh rejection.

### FE-H6 — TWR displayed 100× too small — HIGH — V

`frontend/src/screens/portfolio/PortfolioDetailScreen.tsx:36-40,286`;
`frontend/src/graphql/client.ts:89-123`
Backend TWR is a fraction (`0.20`); `formatPercent` appends `%`. A 20% TWR renders `+0.20%`.
The integration fixture locks it in.
**Fix:** multiply by 100 at the boundary; fix the fixture.

### FE-H7 — Benchmark returns/alpha/tracking error 100× too small — HIGH — S

`frontend/src/screens/portfolio/BenchmarkScreen.tsx:290-296,326,345`
Backend sends fractions (`0.125`); the screen renders `0.125%` while the chart ×100s the same
data — the chart and the cards visibly disagree. Fixture uses percentage-style numbers.
**Fix:** normalise fractions; fix the fixture.

### FE-H8 — Receipt list silently capped at 50 → wrong "all receipts" totals — HIGH — S

`frontend/src/hooks/useReceipts.ts:45-68`; `frontend/src/services/receipts.ts:98-103`
`list()` defaults to `limit=50`; `total` is discarded. Home ("Across all scanned receipts")
and Summary analytics are permanently wrong above 50 receipts.
**Fix:** paginate to `total`, or add a server-side aggregate endpoint.

### FE-H9 — `getCAGR` is a 1-year CAGR presented as full-history — HIGH — S

`frontend/src/services/projectionService.ts:20-35`; `backend/src/market/router.py:113-116`
OHLCV defaults to `today - 365 days`, yet the 5Y/10Y/20Y cards extrapolate it.
**Fix:** request a long window, or label the metric as 1-year and stop extrapolating.

### FE-H10 — Historical projections ignore the selected period — HIGH — S

`frontend/src/hooks/useReceiptProjections.ts:207-248,27-35`
One 1-year CAGR is re-keyed under every period; only the exponent changes. The correct
`getHistoricalCAGRForPeriod` is used only for the future carousel.
**Fix:** call the period-aware function, or fetch one series and derive all periods.

### FE-H11 — Device lock is bypassed on cold start — HIGH — S

`frontend/src/contexts/AuthContext.tsx:119-120,128-165`
`locked` starts `false` and is only set on an active→background transition. Force-quit and
relaunch renders `MainTabs` with no Face ID/passcode.
**Fix:** on mount, set `locked = true` when a session exists and device auth is enabled.

### FE-H12 — Encryption key uses node-forge's weak RNG — HIGH — S

`frontend/src/utils/crypto.ts:7-9`; `frontend/src/services/keyManager.ts:39`
`forge.random.getBytesSync` seeds from `globalScope.crypto.getRandomValues`, which Hermes does
not define and nothing polyfills, so it falls back to Date/navigator entropy. Jest runs under
Node, so tests pass while device keys are predictable.
**Fix:** `expo-crypto.getRandomBytesAsync(32)`.

### FE-H13 — Plaintext password stored in SecureStore, unused, survives sign-out — HIGH — S

`frontend/src/hooks/useDeviceAuth.ts:47-66`; `frontend/src/screens/LoginScreen.tsx:57`;
`frontend/src/screens/SignUpScreen.tsx:66`; `AuthContext.tsx:278-299`
`saveDeviceCredentials` persists the password on every login; `getDeviceCredentials` is never
called; `signOutUser` does not clear it.
**Fix:** delete both functions and the stored value.

### FE-H14 — In-flight refresh can resurrect a signed-out session — HIGH — S

`frontend/src/services/api.ts:54-72,349-357`; `AuthContext.tsx:290`
`signOutUser` clears tokens without cancelling `refreshPromise`; a refresh completing
afterwards writes fresh tokens back. A new login can be overwritten by the old refresh.
**Fix:** generation/epoch counter checked before persisting.

### FE-H15 — 10Y/20Y OHLCV silently truncated (same root cause as BE-D3) — HIGH — S

`frontend/src/services/projectionService.ts:77-93`; `backend/src/market/repository.py:15-45`
The first 2 000 rows of a 2 500–5 000-row window are returned, but the code divides by the
label's years. 10Y/20Y cards use stale data with an overstated exponent.
**Fix:** fix BE-D3; compute `years` from the actual first/last dates.

### FE-H16 — Benchmark chart scales each series independently — HIGH — S

`frontend/src/screens/portfolio/BenchmarkScreen.tsx:76-94`
Per-series min/max in `toPoints`, combined min/max on the axis. Two series with different
ranges are both drawn across the full height, implying a comparison the data does not support.
**Fix:** one shared min/max.

### FE-H17 — One receipt screen fires ~40 API calls; period taps fire 10 more — HIGH — S

`frontend/src/hooks/useReceiptProjections.ts:211-220,251-279,286-306`;
`projectionService.ts:120-126`
10 historical + 10 predictions + 10 discarded CAGRs + 10 window CAGRs. The backend limit is
100/min, so 2–3 period taps can 429 and silently fall back. `historical-updated` fires another
10 on every portfolio mutation because emitters send `{action}`, not `{symbol}`.
**Fix:** per-ticker cache; fetch each OHLCV once; call `getPrediction` directly for badges;
debounce and filter events.

### FE-H18 — `npm start` / `ios` / `android` cannot start the app — HIGH — V

`package.json:6-8`
`cd frontend && expo start`, but there is no `frontend/package.json` or `frontend/app.json`
— both live at the root. `npx expo config` fails with `ConfigError`.
**Fix:** run Expo from the root, or add the frontend config files.

### Frontend — MEDIUM

| ID     | Finding                                                                                                               | File:line                                                                        | Fix                                                      |
| ------ | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------- |
| FE-M19 | Home/Summary ignore `error`, so a failed load renders the "no receipts" onboarding                                    | `hooks/useReceipts.ts:103`; `HomeScreen.tsx:61`; `SummaryScreen.tsx:58`          | error state + Retry                                      |
| FE-M20 | `refetch()` returns `void`, so pull-to-refresh stops instantly                                                        | `hooks/useReceipts.ts:99-101`; `HomeScreen.tsx:102-106`                          | return the promise                                       |
| FE-M21 | Summary refetches categories + recomputes analytics every 30 s                                                        | `SummaryScreen.tsx:61-148,182-192`; `useReceipts.ts:79`                          | deep-equal bail-out; one-shot category load              |
| FE-M22 | Home does N+1 performance requests despite a bulk endpoint                                                            | `HomeScreen.tsx:77-79`; `portfolios.ts:337-342`                                  | use `getBulkPerformance`                                 |
| FE-M23 | Home total goes stale after portfolio actions                                                                         | `HomeScreen.tsx:98-100`                                                          | `useFocusEffect` / subscribe                             |
| FE-M24 | Benchmark requests can resolve out of order; stale data under new labels                                              | `BenchmarkScreen.tsx:207-234`                                                    | sequence/abort                                           |
| FE-M25 | Benchmark failures only `console.warn`; hidden screen polls forever                                                   | `BenchmarkScreen.tsx:207-247`                                                    | error UI; gate on focus                                  |
| FE-M26 | GraphQL HTTP never refreshes a rejected token                                                                         | `graphql/client.ts:17-37`                                                        | 401 → shared refresh + retry                             |
| FE-M27 | Shared WS socket never disposed on logout                                                                             | `graphql/subscriptionClient.ts:32-46,67-71`                                      | export+call `dispose`                                    |
| FE-M28 | Portfolio created then reported as failed if deposit fails → duplicate on retry                                       | `CreatePortfolioScreen.tsx:46-62`                                                | best-effort deposit message, or transactional create     |
| FE-M29 | Loading a past conversation drops reasoning and tool results (reads raw fields after normalisation)                   | `AgentChatScreen.tsx:327-344`; `services/agent.ts:192-203`                       | use the service's mapped objects                         |
| FE-M30 | New chat / history during streaming mixes responses                                                                   | `AgentChatScreen.tsx:358-364,423,327`                                            | disable during load, or abort                            |
| FE-M31 | No cancellation or timeout on chat/scan/API/refresh                                                                   | `services/agent.ts:60-67`; `receipts.ts:171-178`; `api.ts:79-83,197-201,287-291` | `AbortSignal` + timeouts; always settle `refreshPromise` |
| FE-M32 | Device-auth availability ignores enrollment; unlock button always shown                                               | `hooks/useDeviceAuth.ts:10-25`; `LockScreen.tsx:129-137`                         | `isEnrolledAsync()` + prop                               |
| FE-M33 | `keyManager.getOrCreateKey` first-use race and silent new-key fallback                                                | `services/keyManager.ts:20-49`                                                   | serialise with a module promise; fail loudly             |
| FE-M34 | Local cache URI written into `receipt_image_s3_key`                                                                   | `useReceiptCapture.ts:68,152-154`; `useReceipts.ts:57`                           | upload to object storage, or keep local-only             |
| FE-M35 | Camera captures base64 that is never used                                                                             | `ScanScreen.tsx:36,108-111`                                                      | drop `base64: true` + state                              |
| FE-M36 | "Clear All Data" deletes server data but says device-local; no refresh event; partial delete under rate limit         | `SettingsScreen.tsx:132-158`; `services/receipts.ts:150-163`                     | correct copy, emit event, paginate/bulk endpoint         |
| FE-M37 | Zero-total receipts render `NaN%`                                                                                     | `useReceiptProjections.ts:27-35,98-115`                                          | guard `totalAmount > 0`                                  |
| FE-M38 | Home/benchmark pollers keep running while hidden                                                                      | `useReceipts.ts:79,93-97`; `BenchmarkScreen.tsx:237-247`                         | `useFocusEffect` + `AppState`                            |
| FE-M39 | Chat LSTM card reads `prediction`; backend returns `direction`                                                        | `components/chat/ToolResultRenderer.tsx:509-529`                                 | `data.direction ?? data.prediction`                      |
| FE-M40 | Chat performance/benchmark cards render fractions as percentages; gain boxes use non-existent keys                    | `ToolResultRenderer.tsx:198-235,259-277`                                         | ×100; `total_unrealised_pl(_pct)`                        |
| FE-M41 | Quote renderer labels native prices as GBP                                                                            | `ToolResultRenderer.tsx:430-447`                                                 | pass `data.currency`                                     |
| FE-M42 | Confirmation alert offers "Confirm" with no detected amount → £0 receipt                                              | `components/ConfirmationPrompt.tsx:24-55`                                        | omit Confirm                                             |
| FE-M43 | Deprecated `SecureStore.ALWAYS_THIS_DEVICE_ONLY` used for the key/credentials                                         | `useDeviceAuth.ts:50,53,81`; `keyManager.ts:42`                                  | `WHEN_UNLOCKED_THIS_DEVICE_ONLY`                         |
| FE-M44 | Legacy `Swipeable` (deprecated in RNGH 2.28) and no `GestureHandlerRootView`                                          | `ConversationListItem.tsx:11,48`; `App.tsx:26-30`                                | add root view; Reanimated version or accept              |
| FE-M45 | Dead `ocrService` still pulls `expo-image-manipulator`; uses deprecated `manipulateAsync`                             | `services/ocrService.ts:174-189`                                                 | delete module + dependency                               |
| FE-M46 | Unused/deprecated deps: `expo-constants`, `expo-font`, `expo-image-manipulator`, `expo-random`, `expo-sqlite`, `uuid` | `package.json:28,30,32,35,37,47`                                                 | remove; `expo install --check`                           |
| FE-M47 | `@testing-library/jest-native` deprecated and overrides RNTL 14 matchers                                              | `frontend/jest.setup.ts:9`                                                       | remove import + dep                                      |

### Frontend — LOW

| ID     | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                               | File:line                                                                                                       |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| FE-L48 | Dead exports/props: `projectUsingHistoricalCAGR`, `getLSTMPrediction`, `validateAmount`, `parseAmountFromOcrText`, ~8 `portfolios.ts` functions, `checkHealth`, `isAuthenticated`, `getDeviceCredentials`, `encryptString`, `clearKey`, `lightTheme`/`darkTheme`, unused props/styles in `ReceiptCard`/`StockCard`/`StatCard`/`PageHeader`, write-only `portfolioLoading/Error`, unreachable `Array.isArray` branch, unreachable `BackButton` warning | see area report; files span `services/*`, `hooks/*`, `components/*`, `screens/*`                                |
| FE-L49 | `responsive.ts` captures `Dimensions.get('window')` at module load; tokens never rescale on rotation                                                                                                                                                                                                                                                                                                                                                  | `utils/responsive.ts:12-28`                                                                                     |
| FE-L50 | `Animated.createAnimatedComponent` called during render → 18 candles remount                                                                                                                                                                                                                                                                                                                                                                          | `OnboardingScreen.tsx:148-149`                                                                                  |
| FE-L51 | `YearSelector` indicator width stays stale after resize                                                                                                                                                                                                                                                                                                                                                                                               | `YearSelector.tsx:47-50,65-78`                                                                                  |
| FE-L52 | Navigation params bypassed with `as any`/`as never`; `Receipt` lacks `transaction_date`/`notes`                                                                                                                                                                                                                                                                                                                                                       | `useReceiptCapture.ts:77,164`; `HomeScreen.tsx:214,381`; `ReceiptDetailsScreen.tsx:57,381`; `ScanScreen.tsx:32` |
| FE-L53 | Home cards never show OCR source or time (`source` missing from backend response; `time: ''`)                                                                                                                                                                                                                                                                                                                                                         | `hooks/useReceipts.ts:56-58`; `backend/src/receipts/models.py:120-133`                                          |
| FE-L54 | `useReceiptProjections` mutates nested state maps                                                                                                                                                                                                                                                                                                                                                                                                     | `useReceiptProjections.ts:221-227`                                                                              |
| FE-L55 | Failed period refresh keeps old rates under the new label; loading/error write-only                                                                                                                                                                                                                                                                                                                                                                   | `useReceiptProjections.ts:286-306`                                                                              |
| FE-L56 | `formatRelativeDate` emits negative strings for future timestamps                                                                                                                                                                                                                                                                                                                                                                                     | `utils/formatters.ts:42-50`                                                                                     |
| FE-L57 | Legacy `expo-file-system` API path for a decrypt flow the app never creates                                                                                                                                                                                                                                                                                                                                                                           | `utils/fileCrypto.ts:1`                                                                                         |

**Tests that currently encode bugs** (fix the fixture when fixing the code):
`PortfolioDetailScreen.integration.test.tsx:47,200` (TWR), `BenchmarkScreen.integration.test.tsx:55-57,138-153`
(fractions), `ToolResultRenderer.unit.test.tsx:393-406` (`prediction`), `quoteMerge.unit.test.ts:`
(USD price treated as GBP).

---

# 6. Infrastructure, CI, dependencies

### INF-C1 — Live credentials committed in `terraform/tfplan` — CRITICAL — V

`terraform/tfplan` (tracked, 116 960 bytes); `.gitignore:75`
The file is a zip containing `tfstate` and `tfstate-prev`. Verified: 67 occurrences of
`password`, 16 of `jwt_secret`, 24 of `secret_string`, 6 of `DATABASE_URL`. It contains the
RDS master password + endpoint. `.gitignore` has `*.tfplan`, which does not match a filename
with no extension.
**Fix:** `git rm --cached`; add `tfplan`/`*.plan`; purge history with `filter-repo`; **rotate
RDS and JWT secret**; add a gitleaks rule for state/plan archives.

### INF-C2 — Airflow drops the backend's Alembic head on every boot — CRITICAL — V

`airflow/scripts/drop_alembic_version.py:18`; `terraform/modules/airflow/main.tf:233,259`
Backend, Airflow and MLflow share one database and one `public` schema
(`locals.tf:24-34`). Both Airflow tasks run `DROP TABLE IF EXISTS alembic_version CASCADE`
before `airflow db migrate`, on every webserver/scheduler restart, racing each other and
deleting the backend's head.
**Fix:** separate database/schema for Airflow; delete the script.

### INF-C3 — OCR key committed, plus keys in history, and gitleaks allowlists `.env` — CRITICAL — V

`app.json:26`; `.gitleaks.toml:4-8`; commits `8296c35`, `f04ea30`
`git show 8296c35:.env` yields a Firebase web key, an Alpha Vantage key and the OCR key. The
allowlist covers the whole `.env` path, so future leaks are also suppressed.
**Fix:** rotate all keys; scope the allowlist to the historical commit (or remove); do not
allowlist `.env`.

### INF-H1 — CI applies dev variables into the production state key — HIGH — S

`.github/workflows/deploy.yml:351`; `terraform/main.tf:32-38`
`-var="environment=dev"` with all `-dev` resource names, writing to
`stocklens/production/terraform.tfstate`.
**Fix:** derive environment from the ref; key state per workspace.

### INF-H2 — OIDC trust accepts any branch with near-admin rights — HIGH — S

`terraform/modules/iam/main.tf:440-456,476-505`; `.github/workflows/eval.yml:25-27,80-88`
`sub = repo:${github_repo}:*` and a policy with `iam:*`, `s3:*`, `ec2:*`, `kms:*`, `rds:*` on
`*`. Any branch with `id-token: write` can take the account. `eval.yml` already runs on
`pull_request` with that permission; the only gate is a repo variable.
**Fix:** restrict `sub` to `refs/heads/main` + the production environment; split the policy.

### INF-H3 — No TLS anywhere in the request path — HIGH — S

`terraform/modules/compute/main.tf:289-355`; `network/main.tf:18-39`
Port 80 open to the world, HTTP-only listener and target group, HTTPS ingress commented out.
**Fix:** ACM cert, 443 listener with a TLS 1.3 policy, 80→301, HTTPS target group.

### INF-H4 — RDS password in plaintext ECS environment/command — HIGH — S

`terraform/modules/mlflow/main.tf:48,58-75,171-176`;
`terraform/modules/airflow/main.tf:57-59,147-154,173-175,350-352,445-447`
Visible via `ecs:DescribeTaskDefinition`, in process args and in state. Bypasses the Secrets
Manager pattern `database/main.tf` already uses.
**Fix:** `secrets = [{ name, valueFrom }]`; drop the inline `psycopg2.connect`.

### INF-H5 — JWT signing secret copied into a SageMaker model — HIGH — S

`terraform/modules/sagemaker/main.tf:17-19,43`
Read at plan time and written to `primary_container.environment`; visible via
`sagemaker:DescribeModel` and persisted in state. The endpoint never mints JWTs.
**Fix:** remove it.

### INF-H6 — EFS is unreachable (no NFS ingress rule) — HIGH — S

`terraform/modules/compute/main.tf:603-609`; `airflow/main.tf:490-523`
Mount targets use `ecs_tasks_sg`, but no rule allows 2049/2998/2999 anywhere. Mounts hang.
**Fix:** self-referencing rule on 2049 (+2998/2999).

### INF-H7 — Nested `.env` is baked into the Airflow image — HIGH — V

`.dockerignore:19-21`; `airflow/Dockerfile:103`; `deploy.yml:156`
`.env`/`.env.*` match only the root, so `backend/.env` (present, 1 427 bytes) ships in the
image pushed to ECR.
**Fix:** `**/.env`, `**/.env.*`, `**/.aws`.

### INF-H8 — ML image cannot execute Python — HIGH — V (same as ML-C3)

### INF-H9 — `ghcr.io/astral-sh/uv:latest` in three builds — HIGH — S

`backend/Dockerfile:64`; `airflow/Dockerfile:55`; `backend/ml/Dockerfile:48,89`
**Fix:** pin a version or digest.

### INF-H10 — Autoscaled ECS resets to `desired_count` on every apply — HIGH — S

`terraform/modules/compute/main.tf:496-540,545-551`
**Fix:** `lifecycle { ignore_changes = [desired_count] }`.

### Infrastructure — MEDIUM

| ID      | Finding                                                                                                | File:line                                                                                                           | Fix                                    |
| ------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| INF-M1  | Prod stateful defaults: 1-day backups, no PI, `environment` defaults to `production`                   | `modules/database/main.tf:41,54-55`; `variables.tf:15`                                                              | 7–35 days, PI on, default dev          |
| INF-M2  | Redis single node, no failover, engine 7.1 (dev compose runs 8.8)                                      | `modules/cache/main.tf:22-34`; `docker-compose.yml:39`                                                              | 2+ nodes, auto-failover, align version |
| INF-M3  | Receipts expire in 90 days; noncurrent versions never expire                                           | `modules/s3/main.tf:91-104,220-225`                                                                                 | match statutory retention              |
| INF-M4  | WAF lacks `AWSManagedRulesCommonRuleSet`                                                               | `modules/waf/main.tf:36-96`                                                                                         | add OWASP rules                        |
| INF-M5  | Always-on SageMaker endpoint for an off-by-default path; network isolation contradicts S3 download     | `modules/sagemaker/main.tf:27,36,96-100`; `iam/main.tf:534-560`                                                     | serverless/scale-to-zero; resolve      |
| INF-M6  | `AmazonSageMakerFullAccess` attached                                                                   | `modules/iam/main.tf:529-532`                                                                                       | least privilege                        |
| INF-M7  | `ecs:RunTask` on `Resource = "*"`                                                                      | `modules/iam/main.tf:245-255`                                                                                       | scope to cluster/task defs             |
| INF-M8  | Airflow comment says 3.12; image is 3.14                                                               | `airflow/Dockerfile:2,8,38`                                                                                         | decide and pin                         |
| INF-M9  | Airflow deps unbounded; `requirements.txt` drifted from the Dockerfile                                 | `airflow/Dockerfile:73-91`; `airflow/requirements.txt`                                                              | lock/constraints                       |
| INF-M10 | Airflow image runs as root                                                                             | `airflow/Dockerfile:38-122`                                                                                         | non-root user                          |
| INF-M11 | `ENABLE_XCOM_PICKLING = True`                                                                          | `modules/airflow/main.tf:124-127`                                                                                   | remove                                 |
| INF-M12 | `airflow_image` default 2.11 while task commands are 3.x only                                          | `terraform/variables.tf:46`; `modules/airflow/main.tf:100-101,233`                                                  | default 3.x/require                    |
| INF-M13 | SQLite is the baked-in Airflow backend default                                                         | `airflow/Dockerfile:108`                                                                                            | remove                                 |
| INF-M14 | MLflow `pip install psycopg2-binary` at container start; MLflow 2.x                                    | `modules/mlflow/main.tf:46,48,169,171`                                                                              | bake deps; upgrade                     |
| INF-M15 | `JWT_PRIVATE_KEY` never provisioned; each task mints its own RSA key → ~50% MCP auth failure           | `compute/main.tf:388-405`; `src/mcp/auth.py:201-212`                                                                | Secrets Manager PEM                    |
| INF-M16 | tfsec archived; binaries without checksums; no `terraform validate`                                    | `ci.yml:292-320`                                                                                                    | Trivy IaC + validate                   |
| INF-M17 | Node 20 EOL (Apr 2026)                                                                                 | `.nvmrc:1`; `package.json:18`                                                                                       | Node 22/24                             |
| INF-M18 | Python drift 3.12/3.13/3.14 across pyproject/CI/images                                                 | `pyproject.toml:5`; `ci.yml:122,167,253`; `eval.yml:92`; `backend/Dockerfile:8,62,81`                               | align                                  |
| INF-M19 | `dev.auto.tfvars.json` auto-loads dev VPC/email/localhost CORS into every run                          | `terraform/dev.auto.tfvars.json`                                                                                    | rename + `-var-file`                   |
| INF-M20 | Mutable ECR tags + `:latest` pushes                                                                    | `compute/main.tf:56`; `deploy.yml:120,164,204,244`                                                                  | IMMUTABLE, drop latest                 |
| INF-M21 | `npm audit …                                                                                           |                                                                                                                     | true` with a critical open             | `ci.yml:100-104` | allowlist + `--audit-level` |
| INF-M22 | Hardcoded `/Users/ahmedikram/...` and `/tmp/ml_venv` in the Makefile; `train-all` passes an unread var | `Makefile:52-57,65-76,79,82`                                                                                        | `$(CURDIR)`, overridable vars          |
| INF-M23 | Pre-commit Terraform hook checks nothing (`pass_filenames: false` in the repo root)                    | `.pre-commit-config.yaml:46-54`                                                                                     | `fmt -check -recursive terraform/`     |
| INF-M24 | gitleaks allowlists all `.env`                                                                         | `.gitleaks.toml:4-8`                                                                                                | scope to commit                        |
| INF-M25 | Tasks get public IPs in the default VPC; no NAT/VPC endpoints                                          | `compute/main.tf:512-519`; `mlflow/main.tf:128-134`; `airflow/main.tf:279-285,307-312`; `dev.auto.tfvars.json:2-12` | private subnets + endpoints            |
| INF-M26 | State bucket has no public-access block; DynamoDB lock table unused                                    | `terraform/scripts/bootstrap-state.sh:11-29`                                                                        | block public access; drop table        |
| INF-M27 | Budget alarms can reach nobody when `alert_email` is empty                                             | `modules/budgets/main.tf:14-28`; `modules/monitoring/main.tf:15-20`                                                 | fail plan in prod                      |

### Infrastructure — LOW

- Dead locals `champion_prefix_arn`, `private_subnet_ids_json` (`terraform/locals.tf:21,37`).
- Dead variables: `budgets.budget_sns_arn`, `waf.rate_limit_action`, `monitoring.alb_arn_suffix`,
  `cache.vpc_id`, `database.vpc_id`.
- Vestigial module lock files pin conflicting providers (`modules/compute/.terraform.lock.hcl`
  aws 6.71.0, `modules/sagemaker/.terraform.lock.hcl` 6.54.0, root 6.72.0) — delete.
- `terraform/outputs.tf:121-124` returns the literal `"Enabled"` instead of the resource
  attribute; empty `lifecycle {}` at `compute/main.tf:206-209`.
- `ci.yml:119` uses `matrix.target` with no matrix; no `timeout-minutes` on any `ci.yml`/
  `eval.yml` job; Postgres 16 in `eval.yml:51` vs 18 elsewhere; `uv sync` without `--frozen`
  (`eval.yml:103`).
- Stale `.checkov.yml` comment and likely-unread config path; backend Dockerfile `pip install
-e .` as root and duplicated `COPY sagemaker/`; compose publishes datastores with weak
  passwords and `ml` pip-installs floating versions at runtime; CloudWatch retention 365 days
  on four groups; codegen majors behind (`@graphql-codegen/cli` 7→8, `typescript` 6→7,
  `@types/jest` 29→30); third-party actions tag-pinned rather than SHA-pinned (only
  `codeql.yml` pins by SHA).

---

# 7. “Nov 2026” currency audit

Verified deprecations/EOLs found in this repo (each also appears above):

| Item                                  | Where                                                                      | State in Nov 2026                                                            |
| ------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Node 20                               | `.nvmrc`, `package.json` engines, all CI jobs                              | EOL April 2026 → move to 22/24 LTS                                           |
| `expo-random`                         | `package.json:37`                                                          | deprecated → `expo-crypto`                                                   |
| `@testing-library/jest-native`        | `jest.setup.ts:9`                                                          | unmaintained since 2022; RNTL 14 auto-registers matchers                     |
| RNGH legacy `Swipeable`               | `ConversationListItem.tsx:11`                                              | deprecated in 2.28 → Reanimated version                                      |
| `ImageManipulator.manipulateAsync`    | `ocrService.ts:174`                                                        | deprecated in expo-image-manipulator 14 → `manipulate`/`useImageManipulator` |
| `expo-file-system/legacy`             | `utils/fileCrypto.ts:1`                                                    | compatibility path → new `File`/`Directory` API                              |
| `SecureStore.ALWAYS_THIS_DEVICE_ONLY` | `useDeviceAuth.ts`, `keyManager.ts`                                        | deprecated → `WHEN_UNLOCKED_THIS_DEVICE_ONLY`                                |
| tfsec                                 | `ci.yml:310`                                                               | archived → Trivy                                                             |
| MLflow 2.20.3 image                   | `modules/mlflow/main.tf`                                                   | 3.x GA since mid-2025                                                        |
| Redis 7.1 single node                 | `modules/cache/main.tf`                                                    | Redis 8 is current; no failover                                              |
| Airflow 3 config sections             | `airflow/config/airflow.cfg`, `airflow/Dockerfile:109`                     | `[dag_processor]`, not `[scheduler]`                                         |
| Airflow 3 import paths                | `weekly_retraining.py:29-32`                                               | `airflow.sdk`, `airflow.providers.standard.*`                                |
| MCP SDK                               | `pyproject.toml:50`                                                        | installed 2.3.0 renamed `FastMCP`→`MCPServer`; the `<3` pin admits it        |
| Python interpreter                    | pyproject/Dockerfiles/CI                                                   | 3.12/3.13/3.14 all in play — CI does not test what ships                     |
| `yfinance` news schema                | `agent/tools.py:861`                                                       | nested `content` shape since 1.x                                             |
| `pandas` floors                       | `pyproject.toml:28` (`>=2.3`) vs `airflow/requirements.txt:10` (`>=3.1.1`) | two incompatible universes                                                   |
| `langchain-core` floor                | `pyproject.toml:24` (`>=0.3.0`)                                            | incompatible with `langgraph>=1.0`                                           |
| Third-party Actions                   | all workflows                                                              | mostly tag-pinned; only `codeql.yml` SHA-pins                                |

---

# 8. Cross-cutting themes

1. **Two sources of truth for the schema** (`_FIX_SQL`, `database/schema.py`, migrations).
   Drift is already real; every "repair" makes it worse. Pick Alembic and delete the others.
2. **Currency is modelled as a string with a fallback to GBP.** Pence collapse (BE-D2),
   buy-time FX freeze (BE-D12), fail-open FX (BE-D11), client-side native-price overlay
   (FE-C4), and cost-basis-vs-market-value mixes (BE-M27) are five faces of the same design
   gap. One `Money` type with explicit minor units and a valuation date would close all five.
3. **Fraction vs percent is not a contract.** Backend returns fractions, three frontend layers
   append `%` (FE-H6, FE-H7, FE-M40). Define it once.
4. **"Newest N" is consistently written as `ORDER BY ASC LIMIT n`.** OHLCV (BE-D3), agent
   messages (BE-D7), receipt lists (FE-H8). Same bug, three features.
5. **Fail-open error handling at trust/data boundaries.** `.env` guard, FX, Bedrock
   classification, MCP error reporting, Airflow migration catch. Each converts a loud failure
   into a silent wrong result.
6. **The security perimeter is missing TLS, has an over-broad OIDC role, and stores secrets in
   three weaker places than the one it already uses.** Fix the perimeter before feature work.
7. **CI validates a different runtime than production ships** (Python 3.13 vs 3.14, Node 20,
   unfrozen `uv sync`, requirements drift). This is how the ML image mismatch survived.
8. **Tests encode bugs.** TWR, benchmark fractions, LSTM `prediction`, quote currency, and the
   drift handler's fake `drift.*` modules. Fix these first or the fixes will be reverted by the
   suite.

---

# 9. Verification and scope notes

- Findings marked `V` were re-read by the consolidating reviewer. Everything else is a
  source-read with exact citations by the area reviewer.
- No tests, builds, `terraform plan/apply`, or app runs were executed. Claims that depend on
  runtime (ML image interpreter, Bedrock envelope rejection, RNG on Hermes) are derived from
  source and installed library code, not execution.
- No files were modified.
- Out of scope: `backend/tests/` and `frontend/src/__tests__/` were read only to check whether
  they mask the bugs above (four do, listed at the end of §5). The Rust feature engine was
  checked only for causality of `vol_rank`, not numerical parity.
- Deliberate non-fixes recorded in earlier decision records were not re-raised as findings:
  branch protection, local dev CORS, the per-pod refresh grace period, and the documented
  dialect differences are decisions, not defects.
