# StockLens — Implementation Tracker

> **Purpose:** Single source of truth for implementation progress. Agents read this to determine what to work on next, and write to it when done.
> **Plan docs:** [MASTER_PLAN.md](MASTER_PLAN.md) (architecture), [PHASE1_IMPLEMENTATION.md](PHASE1_IMPLEMENTATION.md), [PHASE2_IMPLEMENTATION.md](PHASE2_IMPLEMENTATION.md)
> **Domain glossary:** [CONTEXT.md](CONTEXT.md) (normative terms)
> **Docs are frozen** — plan docs are the specs. This tracker captures what actually happened.

---

## Agent Guidelines for Updating TRACKER.md

When updating this file, agents must follow these rules:

### Step Tracker (the table)

- **DO log:** High-level architectural decisions, key files created, validation results, significant implementation choices
- **DO NOT log:** Bug fixes, typo corrections, minor refactors, "R3.x fix" style entries, implementation details that don't affect architecture
- **Notes column:** Should contain 1-2 sentences summarizing the step's outcome, not a changelog of every fix
- **Keep it concise:** If a note exceeds 2 sentences, it's too detailed

### Deviations Table

- **DO log:** Architectural or strategic deviations from the frozen plan docs (e.g., technology changes, schema additions, version upgrades)
- **DO NOT log:** Bug fixes, implementation corrections, spec compliance fixes, temporary workarounds
- **Criteria:** Ask "Would this change the plan docs if we could go back?" If no, it doesn't belong here

### What Belongs Elsewhere

- Bug fixes and implementation corrections → Tell user in chat
- Temporary workarounds → Code comments or TODOs
- Test failures and fixes → Test files or CI logs

---

---

## Phase 1 — Backend Foundation + Auth + OCR Migration

**Goal:** Eliminate Firebase and Node.js. FastAPI + PostgreSQL is the single backend.
**Cutover:** Big-bang (zero users, no risk).
**Target tests:** 152 pytest (async) + existing 78 Jest (preserved).

### Step Tracker

| #   | Step                                                            | Status      | Notes                                                                                                                                                                                                                                                                                                                                       |
| --- | --------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Project Scaffold & Docker Compose                               | ✅ Complete | Docker Compose with 5 services (postgres, postgres_test, redis, backend, pytest). Backend uses two-stage Dockerfile with uv for dependency management.                                                                                                                                                                                      |
| 2   | Database Schema & Migrations (Alembic)                          | ✅ Complete | Raw asyncpg for runtime queries (no ORM overhead). SQLAlchemy Core MetaData only for Alembic autogeneration. Manual migration with all 10 tables, indexes, and audit triggers.                                                                                                                                                              |
| 3   | Auth Module (JWT + Redis + Rate Limiting)                       | ✅ Complete | JWT auth with access/refresh tokens. Multi-session refresh token rotation with PostgreSQL revocation. Redis blacklisting for stolen token detection. Rate limiting via slowapi with Redis sliding window (20/min auth, 100/min other).                                                                                                      |
| 4   | Portfolio CRUD                                                  | ✅ Complete | Full CRUD with ownership scoping via user_id WHERE clauses. Partial updates via dynamic SET clauses. DELETE returns 204.                                                                                                                                                                                                                    |
| 5   | Holdings CRUD                                                   | ✅ Complete | Nested and standalone routes. Ownership verified via JOIN with portfolios table. Ticker auto-uppercase via field validator.                                                                                                                                                                                                                 |
| 6   | Transactions CRUD                                               | ✅ Complete | Server-side total_amount calculation with DB CHECK constraint. Pagination via limit/offset (max 100). Optional ticker filtering. Transaction date future-check validator.                                                                                                                                                                   |
| 7   | Spending Categories & Merchant Mapping                          | ✅ Complete | 10 seeded categories with keyword mappings. Merchant→category via keyword matching with Bedrock Claude Haiku fallback.                                                                                                                                                                                                                      |
| 8   | OCR Pipeline (OpenCV + pytesseract)                             | ✅ Complete | Regex-first OCR parsing (total, merchant, line items, date). Bedrock Claude Haiku fallback for merchant category classification only.                                                                                                                                                                                                       |
| 9   | Receipt CRUD + OCR Integration                                  | ✅ Complete | Full CRUD with ownership scoping. Scan endpoint persists OCR results to DB with category resolution. Image bytes discarded after processing.                                                                                                                                                                                                |
| 10  | React Native Migration (Auth + API client + Context rewrite)    | ✅ Complete | Firebase SDK replaced with FastAPI HTTP client. AuthContext rewritten with new auth service. `dataService.ts` stripped to stock-only (560 lines dead code removed). `firebase` dependency removed. 31 new unit tests for api.ts + auth.ts (token injection, auto-refresh, error parsing, signUp/signIn/signOut/getProfile/isAuthenticated). |
| 11  | Terraform Provisioning (VPC + RDS + S3 + ECR + Secrets Manager) | ✅ Complete | VPC + S3 modules with conditional VPC creation. 3 S3 buckets with AES256 encryption. 5 Secrets Manager secrets. Skeleton WAF + monitoring modules for Phase 5.                                                                                                                                                                              |
| 12  | Test Suite (Full Coverage)                                      | ✅ Complete | 152 tests across 9 modules covering all Phase 1 functionality. Per-test transaction rollback for isolation.                                                                                                                                                                                                                                 |

### Deviations from Plan

| Step or Round | Planned                                                               | Actual                                       | Rationale                                                                                                                                                         |
| ------------- | --------------------------------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| —             | AWS region defaulted to `us-east-1`                                   | Changed to `eu-west-2` (London)              | User requirement. Updated in `config.py` and `.env.example`. Future steps (Terraform, Bedrock) must use `eu-west-2`.                                              |
| 2             | Autogenerate initial migration with `alembic revision --autogenerate` | Written manually as `0001_initial_schema.py` | Manual DDL gives full control over `gen_random_uuid()`, enum ordering, and downgrade path                                                                         |
| 2             | `is_active` column not present in spec table definition               | Added to migration `0001_initial_schema.py`  | Auth pipeline queries `is_active` in 3 places; column was missing from initial migration. Injected directly into 0001 since no production deployment has run yet. |
| 11            | RDS PostgreSQL version 16                                             | Upgraded to 18.3                             | Initially set to PG 16 (assumed RDS limitation); upgraded to 18.3 after verifying AWS Console supports it                                                         |

### Verification Checklist (Phase 1 DoD)

- [x] `docker compose up -d` succeeds with all services healthy
- [x] User can register, login, refresh, logout via API (backend built + frontend wired)
- [x] Authenticated user can CRUD portfolios, holdings, transactions (endpoints built + ownership-scoped)
- [x] Receipt upload → OCR extracts total, merchant, line items → category assigned + persisted to DB
- [x] React Native app builds and runs against FastAPI (no Firebase) — AuthContext rewritten, `api.ts` + `auth.ts` created, all screens updated (LockScreen included in R3.3)
- [x] All 152 pytest tests pass (`docker compose run --rm pytest` — 152/152 pass)
- [x] All existing 79 Jest tests pass (79/79 — updated for API-based receipt service, zero warnings)
- [x] `ruff check src/ tests/` — zero errors (fixed in R3.2)
- [x] ESLint — zero errors
- [x] `npx tsc --noEmit` — zero errors (confirmed in Step 10)
- [x] `terraform plan -var="environment=dev"` exits 0
- [ ] IaC security scan passes: `checkov --config-file checkov.yml -d terraform/` and `tfsec terraform/` — zero critical/high _(config written, needs `terraform apply` to run full scan)_
- [ ] Secrets Manager: 5 secrets created and accessible by intended IAM roles _(Terraform config written, needs `terraform apply`)_
- [x] Python test coverage ≥80% _(confirmed 84% via `--cov=src`)_

### Security Checklist

- [x] Passwords: bcrypt work factor ≥12
- [x] JWT: HS256 with ≥256-bit secret
- [x] Refresh tokens: SHA256 hash in DB, per-session, rotation active
- [x] Stolen token detection: revoked refresh reuse → all sessions invalidated (implemented in /refresh, tested)
- [x] Logout: revokes specific refresh token + blacklists access token (returns 204, accepts refresh_token in body)
- [x] Receipt images: processed in memory, discarded immediately _(confirmed in `router.py:187` — explicit comment, no write-to-disk code)_
- [x] All DB queries: parameterised (`$1`, `$2` via asyncpg) _(confirmed across all 39 asyncpg queries in src/)_
- [x] Rate limiting: slowapi + Redis sliding window (20/min auth, 100/min other via config.py settings)
- [x] CORS: restricted via `CORS_ORIGINS` env var _(confirmed in `config.py:35` + `main.py:86`)_
- [x] RDS: `storage_encrypted = true`, security group restricted to VPC CIDR _(Terraform config — apply in Phase 5)_
- [ ] Redis: encryption at rest + transit enabled (cache.r6g.micro) _(Terraform config — apply in Phase 5)_
- [x] ECR: immutable tags confirmed in `ecr.tf:8` _(Terraform config — apply in Phase 5)_
- [x] Secrets: all production secrets defined in `secrets.tf` (DATABASE*URL, JWT_SECRET_KEY, BEDROCK_API_KEY, REDIS_PASSWORD, DB_PASSWORD) *(Terraform config — apply in Phase 5)\_
- [x] IaC security: `checkov.yml` config present; runs blocked until `terraform apply` _(needs provisioned resources for full scan)_
- [x] Terraform state: `*.tfstate` files gitignored (local only — **must migrate to S3 backend before production deployment**)

---

## Phase 2 — Market Data & Portfolio Analytics

**Goal:** yfinance integration, OHLCV/quote endpoints, per-holding P&L, TWR (cash-flow-based), benchmark comparison (TE/IR), and cash_flows module for receipt-backed portfolio deposits.
**Cutover:** Additive — Phase 1 endpoints are unchanged, Phase 2 is new capability.
**Target tests:** 80+ new tests across `market/`, `cash_flows/`, and `performance/` modules.

### Step Tracker

| #   | Step                                                                                                                           | Status         | Notes |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | -------------- | ----- |
| R1  | **Round 1 — Market Data Provider**                                                                                             | 🔲 Not started |       |
| 1.1 | Add yfinance + tenacity deps to `pyproject.toml`                                                                               | 🔲 Not started |       |
| 1.2 | Market module skeleton — `market/__init__.py`                                                                                  | 🔲 Not started |       |
| 1.3 | Market schemas — `market/schemas.py` (OHLCVData, QuoteResponse, OHLCVResponse)                                                 | 🔲 Not started |       |
| 1.4 | OHLCV repository — `market/repository.py` (get_ohlcv, upsert_ohlcv via executemany)                                            | 🔲 Not started |       |
| 1.5 | yfinance provider — `market/provider.py` (to_thread, tenacity retry, NaN handling)                                             | 🔲 Not started |       |
| 1.6 | Market router — `market/router.py` (OHLCV + quote endpoints, Redis 60s cache)                                                  | 🔲 Not started |       |
| 1.7 | Register market router in `main.py`                                                                                            | 🔲 Not started |       |
| 1.8 | Market tests — `test_market.py` (25+ tests, yfinance mocked)                                                                   | 🔲 Not started |       |
| R2  | **Round 2 — Cash Flows + Portfolio Analytics**                                                                                 | 🔲 Not started |       |
| 2.1 | Performance schemas — `performance/schemas.py` (HoldingPerformance, PortfolioPerformanceResponse, BenchmarkComparisonResponse) | 🔲 Not started |       |
| 2.2 | Cash flows migration — `0003_add_cash_flows.py` (cash_flows table, index)                                                      | 🔲 Not started |       |
| 2.3 | Cash flows schemas — `cash_flows/schemas.py` (CashFlowCreate, CashFlowResponse)                                                | 🔲 Not started |       |
| 2.4 | Cash flows repository — `cash_flows/repository.py` (create, list, sum, PATCH notes)                                            | 🔲 Not started |       |
| 2.5 | Cash flows router — `cash_flows/router.py` (POST/GET/PATCH at /portfolios/{id}/cash-flows)                                     | 🔲 Not started |       |
| 2.6 | Performance calculations — `performance/calculations.py` (P&L, TWR with cash_flows, daily returns, TE/IR, ENABLE_TWR flag)     | 🔲 Not started |       |
| 2.7 | Performance router — `performance/router.py` (performance + benchmark endpoints, fetches cash_flows, free_cash_balance)        | 🔲 Not started |       |
| 2.8 | Register cash_flows + performance routers in `main.py`; add `ENABLE_TWR` to `config.py`                                        | 🔲 Not started |       |
| 2.9 | Performance + Cash Flows tests — `test_performance.py` (50+ tests), `test_cash_flows.py` (14+ tests)                           | 🔲 Not started |       |
| R3  | **Round 3 — Integration, Tests & Polish**                                                                                      | 🔲 Not started |       |
| 3.1 | Build & test — `docker compose build`, run all 232+ tests                                                                      | 🔲 Not started |       |
| 3.2 | Lint — `ruff check src/ tests/` — zero errors                                                                                  | 🔲 Not started |       |
| 3.3 | Verify API docs — `GET /docs` renders all 6+ Phase 2 endpoints                                                                 | 🔲 Not started |       |
| 3.4 | Update CI — verify test paths include new test files                                                                           | 🔲 Not started |       |
| 3.5 | Update TRACKER.md — log deviations, completion                                                                                 | 🔲 Not started |       |

### Deviations from Plan

| Step or Round | Planned | Actual | Rationale |
| ------------- | ------- | ------ | --------- |
| —             | —       | —      | —         |

### Verification Checklist (Phase 2 DoD)

- [ ] `GET /market/ohlcv/{ticker}` — returns OHLCV data with date range support (cache hit → DB, cache miss → yfinance → DB, tenacity retry on failure)
- [ ] Market data freshness accounts for weekends — 3-day staleness tolerance on Monday
- [ ] `GET /market/quote/{ticker}` — returns current quote with 60s Redis cache
- [ ] Redis outage handled gracefully — quote endpoint returns fresh data from yfinance instead of 500
- [ ] `GET /portfolios/{id}/cash-flows` — returns cash flow list (paginated)
- [ ] `POST /portfolios/{id}/cash-flows` — creates deposit, validates amount > 0
- [ ] `PATCH /portfolios/{id}/cash-flows/{cf_id}` — updates notes
- [ ] `GET /portfolio/performance/{portfolio_id}` — returns per-holding P&L + TWR (cash-flow-based) + portfolio aggregate + free_cash_balance
- [ ] `GET /portfolio/benchmark/{portfolio_id}` — returns alpha + tracking error + information ratio (with daily_returns_count)
- [ ] TWR: cash-flow-based methodology, uses cash_flows for external CF amounts, transactions for holdings state only, BMV=0 guard
- [ ] TWR: pre-existing holdings before start_date are correctly seeded from pre-start-date transactions
- [ ] ENABLE_TWR feature flag: when False, TWR/TE/IR return null
- [ ] Tenacity retry: exponential backoff (3 attempts, 1s/2s/4s) on yfinance failures
- [ ] All Phase 1 tests still pass (152/152)
- [ ] 80+ Phase 2 tests pass (25+ market + 14+ cash_flows + 50+ performance)
- [ ] `ruff check src/ tests/` — zero errors
- [ ] `docs/TRACKER.md` updated to reflect Phase 2 completion

---

## Future Phases

### Phase 3 — LSTM & ML Pipeline

_Not started._ Add tracker rows when Phase 3 begins.

### Phase 4 — MLOps & Automation

_Not started._ Add tracker rows when Phase 4 begins.

### Phase 5 — Production AWS Deployment

_Not started._ Add tracker rows when Phase 5 begins.

### Phase 6 — Conversational Agent

_Not started._ Add tracker rows when Phase 6 begins.
