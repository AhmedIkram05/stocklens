# Phase 1 — Backend Foundation + Auth + OCR Migration

> **Parent document:** [MASTER_PLAN.md](MASTER_PLAN.md) > **Status:** Draft
> **Goal:** Eliminate Firebase and Node.js. FastAPI + PostgreSQL is the single backend. All existing app functionality ported and improved.
> **Depends on:** Nothing (greenfield backend — existing Firebase app runs in parallel until cutover)
> **Cutover strategy:** Big-bang (zero users, no risk)

---

## Table of Contents

1. [Scope & Deliverables](#scope--deliverables)
2. [Directory Structure](#directory-structure)
3. [Execution Strategy](#execution-strategy)
   - [Dependency Graph](#dependency-graph)
   - [Key Parallelism Insights](#key-parallelism-insights)
   - [Round-by-Round Execution Plan](#round-by-round-execution-plan)
   - [File Ownership](#file-ownership)
4. [Step-by-Step Implementation](#step-by-step-implementation)
   - [Step 1: Project Scaffold & Docker Compose](#step-1-project-scaffold--docker-compose)
   - [Step 2: Database Schema & Initialisation](#step-2-database-schema--initialisation)
   - [Step 3: Auth Module (JWT + Redis)](#step-3-auth-module-jwt--redis)
   - [Step 4: Portfolio CRUD](#step-4-portfolio-crud)
   - [Step 5: Holdings CRUD](#step-5-holdings-crud)
   - [Step 6: Transactions CRUD](#step-6-transactions-crud)
   - [Step 7: Spending Categories & Merchant Mapping](#step-7-spending-categories--merchant-mapping)
   - [Step 8: OCR Pipeline](#step-8-ocr-pipeline)
   - [Step 9: Receipt CRUD + OCR Integration](#step-9-receipt-crud--ocr-integration)
   - [Step 10: React Native Migration](#step-10-react-native-migration)
   - [Step 11: Terraform Provisioning](#step-11-terraform-provisioning)
   - [Step 12: Test Suite](#step-12-test-suite)
5. [Definition of Done](#definition-of-done)
6. [Verification Checklist](#verification-checklist)

---

## Scope & Deliverables

### In Scope

- Docker Compose environment (FastAPI 0.138.x + PostgreSQL 18 + Redis 8.8)
- JWT auth with access + refresh tokens (body-based, stored in SecureStore on mobile), bcrypt password hashing, multi-session refresh token rotation
- Full CRUD: portfolios, holdings, transactions (Pydantic-validated)
- Spending category seed data and merchant keyword mapping
- OCR pipeline: pytesseract for text extraction + merchant detection + Bedrock Claude Haiku fallback for ambiguous merchants
- Receipt CRUD integrated with OCR output
- 60–80 pytest tests (auth, CRUD, OCR, categories, caching)
- Terraform: RDS (db.t3.micro, Multi-AZ, 7-day backups, PITR) + S3 buckets (3) + ECR repository + Secrets Manager (4 secrets: JWT key, DB URL, Bedrock key, Redis password)
- React Native: Firebase SDK replaced with FastAPI HTTP client
- All existing Jest tests preserved
- AES-256 encryption for financial data at rest

### Out of Scope

- Market data / OHLCV prices (Phase 2)
- LSTM model (Phase 3)
- MLOps / Airflow (Phase 4)
- AWS deployment beyond storage infra (Phase 5)
- Agent (Phase 6)
- S3 receipt storage (stubbed — images stored locally until Phase 5)

### Tech Decisions

| Decision               | Choice                                                           | Rationale                                                                                                                                   |
| ---------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| OCR library            | pytesseract                                                      | Clean receipts (controlled capture). Simpler than PaddleOCR.                                                                                |
| OCR preprocessing      | opencv-python-headless                                           | Adaptive thresholding + denoising for real-world receipts with shadows/angle. CV narrative alignment.                                       |
| OCR LLM fallback       | AWS Bedrock Claude Haiku                                         | Better CV signal than local Ollama. Haiku is fast/cheap for structured classification. Complements AWS-native stack.                        |
| Python package manager | uv                                                               | Faster than pip, modern resolver, same project uses it.                                                                                     |
| Async DB driver        | asyncpg                                                          | Native async PostgreSQL driver. All endpoints `async def` — no event loop blocking.                                                         |
| ORM / SQL              | Raw SQL via asyncpg                                              | No ORM overhead. SQL is explicit and auditable.                                                                                             |
| Migration tool         | Alembic                                                          | Industry-standard schema migrations. Hand-written SQL via `op.execute()`. No SQLAlchemy ORM dependency.                                     |
| Test DB pattern        | Separate `postgres_test` container in Docker Compose             | LAAD pattern. Isolated test database.                                                                                                       |
| Per-test isolation     | Transaction rollback                                             | Fast, clean, industry-standard pattern for asyncpg + pytest.                                                                                |
| Redis usage            | JWT blacklist + rate limiting (sliding window)                   | Same pattern as LAAD. Redis is lightweight and well-understood.                                                                             |
| Rate limiting          | slowapi + sliding window                                         | Fairer than fixed window, ~30 lines of code with Redis sorted sets.                                                                         |
| Terraform scope        | VPC + RDS + S3 + ECR + Secrets Manager + IaC scanning in Phase 1 | VPC provisioned alongside storage infra from day one. Secrets Manager for production-grade secret storage. checkov + tfsec run on every PR. |
| HEIC handling          | iOS-side conversion (Expo ImagePicker)                           | Simpler than server-side pillow-heif. Existing app already converts via expo-image-picker.                                                  |

---

## Directory Structure

Created in the **repository root** (alongside existing `src/`, `App.tsx`, etc.):

```
backend/
├── Dockerfile
├── pyproject.toml
├── alembic/
│   ├── env.py                     # Alembic environment (asyncpg connection)
│   ├── script.py.mako             # Migration template
│   └── versions/                  # Migration scripts, e.g. 001_create_users.py
│       └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app creation, lifespan, CORS
│   ├── config.py                  # pydantic-settings: DB URLs, JWT secret, etc.
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py          # asyncpg connection pool
│   │   └── init_db.py             # Run Alembic migrations on startup
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── router.py              # /auth/register, /auth/login, /auth/refresh, /auth/logout, /auth/me
│   │   ├── dependencies.py        # get_current_user, require_auth
│   │   ├── utils.py               # create_access_token, create_refresh_token, verify_password, hash_password
│   │   └── schemas.py             # RegisterRequest, LoginResponse, TokenRefreshRequest, UserResponse
│   ├── portfolios/
│   │   ├── __init__.py
│   │   ├── router.py              # CRUD: list, create, get, update, delete
│   │   └── schemas.py             # PortfolioCreate, PortfolioUpdate, PortfolioResponse
│   ├── holdings/
│   │   ├── __init__.py
│   │   ├── router.py              # CRUD nested under portfolio: list, create, get, update, delete
│   │   └── schemas.py             # HoldingCreate, HoldingUpdate, HoldingResponse
│   ├── transactions/
│   │   ├── __init__.py
│   │   ├── router.py              # CRUD nested under portfolio: list, create, get
│   │   └── schemas.py             # TransactionCreate, TransactionResponse
│   ├── receipts/
│   │   ├── __init__.py
│   │   ├── router.py              # CRUD + POST /receipts/scan (multipart upload → OCR)
│   │   ├── schemas.py             # ReceiptCreate, ReceiptResponse, ScanResponse
│   │   └── ocr.py                 # OCR pipeline: extract text, parse total, detect merchant
│   ├── categories/
│   │   ├── __init__.py
│   │   ├── router.py              # GET /categories (list all)
│   │   ├── schemas.py             # CategoryResponse
│   │   ├── merchant_map.py        # Keyword mapping dict + Bedrock fallback
│   │   └── seed.py                # Seed default categories into DB
│   └── cache/
│       ├── __init__.py
│       └── redis.py               # Redis connection, get/set/blacklist helpers
├── tests/
│   ├── conftest.py                # Fixtures: test client, test DB, auth headers
│   ├── test_auth.py
│   ├── test_portfolios.py
│   ├── test_holdings.py
│   ├── test_transactions.py
│   ├── test_receipts.py
│   ├── test_ocr.py
│   ├── test_categories.py
│   └── test_cache.py
└── data/                          # gitignored — local receipt image storage
    └── .gitkeep

terraform/
├── provider.tf
├── variables.tf
├── main.tf                        # module calls: secrets, rds, s3, ecr
├── outputs.tf
├── checkov.yml                    # IaC security scan config (checkov)
└── modules/
    ├── secrets/
    │   ├── main.tf                 # AWS Secrets Manager: JWT key, DB URL, Bedrock key, Redis password
    │   ├── variables.tf
    │   └── outputs.tf
    ├── rds/
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── s3/
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    └── ecr/
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
    └── waf/                           # Phase 5 — module created now, provisioned in Phase 5
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
    └── monitoring/                    # Phase 5 — CloudWatch dashboards + Budgets alarms
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
```

---

## Execution Strategy

> How the 12 steps are sequenced to maximise parallelism while respecting dependencies. Read this before reading the individual steps — it explains which agents run when and why.

### Dependency Graph

```
Step 1  (scaffold, Docker Compose, pyproject.toml, config.py, Makefile)
 │
 ├──► Step 2   (database schema, Alembic, connection.py, init_db.py)
 │    ├──► Step 3   (JWT auth, Redis blacklist, refresh rotation, rate limiting)
 │    │    └──► Step 4   (portfolio CRUD)
 │    │         └──► Step 5   (holdings CRUD)
 │    │         └──► Step 6   (transactions CRUD)
 │    ├──► Step 7   (spending categories, merchant keyword mapping)
 │    │    └──► Step 9   (receipt CRUD + OCR integration)
 │    └──► Step 8   (OCR pipeline — OpenCV + pytesseract) ─── pure Python, no DB
 │
 ├──► Step 10  (React Native migration — depends on API contracts, not running backend)
 │
 ├──► Step 11  (Terraform provisioning — VPC, RDS, S3, ECR, Secrets Manager)
 │
 └──► Step 12  (test suite — depends on everything above)
```

### Key parallelism insights

| Insight                                          | Why it matters                                                                                                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Step 8 (OCR) needs no database**               | OpenCV + pytesseract pipeline is pure image processing. It only needs `pyproject.toml` from Step 1. Can run in parallel with schema, auth, and CRUD.                            |
| **Step 11 (Terraform) needs no running backend** | IaC is written from the documented schema, not a live database. Can start as soon as scaffold is done.                                                                          |
| **Step 10 (RN migration) is contract-driven**    | The RN agent writes HTTP calls against PHASE1_IMPLEMENTATION.md's documented schemas, not a running server. Safe to parallelise with backend work.                              |
| **Steps 4+5+6 (CRUD) are mechanical**            | Once auth exists (Step 3), portfolios, holdings, and transactions follow a repeated pattern: async SQL + Pydantic models + ownership verification. One agent handles all three. |

### Round-by-round execution plan

| Round                | Steps                   | Agents             | Rationale                                                                                                                                                                                                                    |
| -------------------- | ----------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1** (sequential)   | Step 1                  | 1 (code-architect) | Hard prerequisite. Scaffold file set is large — Dockerfile (two-stage), docker-compose (5 services), pyproject.toml (22 deps), config.py (12 settings), structlog setup, Makefile. One focused agent avoids context squeeze. |
| **2** (parallel)     | Step 2, Step 8, Step 11 | 3 (general × 3)    | Schema lands in Step 2 before auth needs it. OCR (Step 8) has zero DB dependency. Terraform (Step 11) is fully independent. Three agents, all read-only with respect to each other's files.                                  |
| **3** (parallel)     | Step 3, Step 7, Step 10 | 3 (general × 3)    | Auth needs schema (landed in Round 2). Categories need schema. RN migration needs API contracts (written from doc, not running server). All three agents work from the same source of truth document.                        |
| **4** (parallel)     | Steps 4+5+6, Step 9     | 2 (general × 2)    | CRUD chain needs auth (landed in Round 3). Receipts need categories and OCR. One agent handles the three CRUD modules (they share identical patterns). One agent handles receipts.                                           |
| **5** (sequential)   | Step 12                 | 1 (code-reviewer)  | Test suite depends on all code being written. Agent writes 60–80 tests and runs them.                                                                                                                                        |
| **6** (verification) | Smoke test              | direct             | `make rebuild && make test`. Verify existing Jest tests still pass. Manual curl check of `/health`, `/auth/register`, `/auth/login`.                                                                                         |

### File ownership (which agent writes what)

```
backend/
├── Dockerfile              Round 1
├── pyproject.toml          Round 1
├── .env.example            Round 1
├── Makefile                Round 1
├── docker-compose.yml      Round 1
├── alembic/                Round 2
├── src/
│   ├── main.py             Round 1 (structlog + lifespan skeleton)
│   ├── config.py           Round 1
│   ├── database/           Round 2
│   ├── auth/               Round 3
│   ├── portfolios/         Round 4
│   ├── holdings/           Round 4
│   ├── transactions/       Round 4
│   ├── receipts/
│   │   ├── router.py       Round 4
│   │   ├── schemas.py      Round 4
│   │   └── ocr.py          Round 2
│   ├── categories/         Round 3
│   └── cache/              Round 3
├── tests/                  Round 5
└── data/                   Round 1

terraform/                 Round 2 (all modules)
```

---

## Step-by-Step Implementation

### Step 1: Project Scaffold & Docker Compose

**Round:** 1
**Agent:** code-architect / general

**Task:** Create `backend/` directory structure, `Dockerfile`, `pyproject.toml`, `docker-compose.yml`, and `.env.example`.

**`docker-compose.yml` services:**

| Service       | Image              | Port | Purpose                       |
| ------------- | ------------------ | ---- | ----------------------------- |
| postgres      | postgres:18-alpine | 5432 | Primary database              |
| postgres_test | postgres:18-alpine | 5433 | Test isolation database       |
| redis         | redis:8.8-alpine   | 6379 | JWT blacklist + rate limiting |
| backend       | (build ./backend)  | 8000 | FastAPI application           |
| pytest        | (build ./backend)  | —    | Test runner (profile: test)   |

**Pattern reference:** LAAD project's `docker-compose.yml` — identical structure for postgres, redis, postgres_test, and pytest services. Use `profiles: [test]` for test-only containers.

**`pyproject.toml` dependencies:**

- `fastapi>=0.138.0`
- `uvicorn[standard]`
- `asyncpg>=0.30.0`
- `bcrypt>=5.0.0`
- `pyjwt>=2.13.0`
- `python-multipart>=0.0.18`
- `pydantic-settings>=2.14.0`
- `redis>=5.2.0`
- `slowapi>=0.1.9` (rate limiting with sliding window)
- `alembic>=1.14.0` (database migrations)
- `pytesseract>=0.3.13`
- `opencv-python-headless>=4.10.0` (adaptive thresholding, denoising for OCR)
- `Pillow>=11.0.0`
- `boto3>=1.43.0`
- `langchain-aws>=1.6.0` (Bedrock integration for merchant classification)
- `httpx>=0.28.0`
- `pytest>=8.3.0`
- `pytest-asyncio>=0.24.0` (async test support)
- `pytest-cov>=6.0.0`
- `pytest-mock>=3.14.0`
- `python-dotenv>=1.0.0`
- `structlog>=24.4.0` (structured JSON logging)

> **Version note (2026-06-26):** Pins above verified against current PyPI. Use `uv add` to install — it resolves the latest compatible versions automatically.

**`config.py`** uses `pydantic-settings.BaseSettings`:

- `DATABASE_URL` — defaults to `postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens`
- `TEST_DATABASE_URL` — defaults to `postgresql+asyncpg://stocklens:stocklens@postgres_test:5432/stocklens_test`
- `REDIS_URL` — defaults to `redis://redis:6379/0`
- `JWT_SECRET_KEY` — required, no default
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` — default 30
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS` — default 7
- `AWS_REGION` — default `us-east-1`
- `BEDROCK_MODEL_ID` — default `anthropic.claude-3-haiku-20240307-v1:0`
- `OCR_TESSERACT_CMD` — optional, for Windows compat
- `RATE_LIMIT_LOGIN` — default `20/minute`
- `RATE_LIMIT_DEFAULT` — default `100/minute`
- `STRUCTLOG_LOG_LEVEL` — default `INFO`
- `ENVIRONMENT` — default `development` (set to `production` in ECS)

**Logging configuration (main.py lifespan):** Configure structlog early in app startup:

```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()  # JSON output for CloudWatch log insight
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
```

The JSON log lines flow to stdout, captured by Docker's json-file driver locally and by CloudWatch `awslogs` driver in ECS.

**Docker health checks:**

- PostgreSQL: `pg_isready -U stocklens`
- Redis: `redis-cli ping`
- Backend: `curl -f http://localhost:8000/health`

**`backend/Dockerfile`** — two-stage build (builder + runtime), same pattern as LAAD:

- Stage 1: `python:3.14-slim`, install deps via `uv`
- Stage 2: `python:3.14-slim`, copy site-packages from builder + app source
- Non-root user (uid 1000)
- Install `tesseract-ocr`, `libgl1-mesa-glx`, `libglib2.0-0` (OpenCV runtime deps), and `curl` in runtime stage
- CMD: `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2`

**Makefile** (in repo root, alongside existing npm scripts):

- `make up` — `docker compose up -d`
- `make down` — `docker compose down`
- `make rebuild` — `docker compose build backend && docker compose up -d`
- `make test` — runs pytest in Docker (profile: test)
- `make logs` — `docker compose logs -f`
- `make migrate` — runs Alembic migrations in the backend container: `docker compose exec backend alembic upgrade head`
- `make alembic-autogenerate msg="description"` — generates a new migration revision: `docker compose exec backend alembic revision --autogenerate -m "description"`

---

### Step 2: Database Schema & Migrations (Alembic)

**Round:** 2
**Agent:** code-architect / general

**Task:** Set up Alembic with asyncpg, write the initial migration creating all Phase 1 tables with correct schema (including `refresh_tokens`, corrected `total_amount`, and all indexes).

#### Alembic Setup

**`alembic/env.py`:**

- Configure async SQLAlchemy engine using `DATABASE_URL` (uses `asyncpg` driver)
- Run migrations in `async def run_migrations_online()` — standard Alembic async pattern
- Target metadata from a shared `MetaData` object in `backend/src/database/schema.py`

**`alembic.ini`** (in `backend/`):

- `script_location = alembic`
- `sqlalchemy.url` = placeholder (overridden by `env.py` at runtime)

**`src/database/schema.py`:**

- Shared `MetaData` instance with all table definitions using SQLAlchemy Core (Table, Column, etc.) — NOT the ORM. Used only for Alembic autogeneration, not for runtime queries.
- Runtime queries use raw async SQL via asyncpg.

#### Migration: `001_create_initial_tables.py`

Generated via `alembic revision --autogenerate -m "create_initial_tables"`, then hand-verified.

All Phase 1 tables, with key schema corrections vs. the original plan:

| Table                 | Key Details                                                                                                                                                                                                                                                                        |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `users`               | id UUID PK, email UNIQUE, password_hash, display_name, created_at, updated_at                                                                                                                                                                                                      |
| `refresh_tokens`      | id UUID PK, user_id FK, token_hash VARCHAR(64) UNIQUE, expires_at, revoked DEFAULT FALSE, created_at                                                                                                                                                                               |
| `portfolios`          | id UUID PK, user_id FK CASCADE, name, description, timestamps                                                                                                                                                                                                                      |
| `holdings`            | id UUID PK, portfolio_id FK CASCADE, ticker VARCHAR(10), shares DECIMAL(18,6), average_cost_basis DECIMAL(12,4), UNIQUE(portfolio_id, ticker), timestamps                                                                                                                          |
| `transactions`        | id UUID PK, portfolio_id FK CASCADE, ticker VARCHAR(10), type VARCHAR(4) CHECK ('BUY','SELL'), shares DECIMAL(18,6), price_per_share DECIMAL(12,4), **total_amount DECIMAL(24,6) NOT NULL, CHECK (total_amount = shares \* price_per_share)**, transaction_date, notes, created_at |
| `receipts`            | id UUID PK, user_id FK CASCADE, total_amount DECIMAL(10,2), merchant_name, category_id FK, ocr_raw_text, ocr_confidence REAL, line_items JSONB, receipt_image_s3_key, scanned_at, created_at                                                                                       |
| `spending_categories` | id UUID PK, name UNIQUE, description, merchant_keywords JSONB, associated_tickers JSONB                                                                                                                                                                                            |
| `ohlcv_prices`        | id BIGSERIAL PK, ticker, date, open/high/low/close/adjusted_close DECIMAL(12,4), volume BIGINT, UNIQUE(ticker, date) — created now, populated in Phase 2                                                                                                                           |
| `model_registry`      | id BIGSERIAL PK, ticker, mlflow_run_id, model_version, alias, metrics — created now, populated in Phase 3                                                                                                                                                                          |
| `agent_conversations` | id BIGSERIAL PK, user_id FK CASCADE, message, response, tools_used JSONB, reasoning_steps JSONB, created_at — created now, populated in Phase 6                                                                                                                                    |

**Indexes (in the same migration):**

- `idx_portfolios_user_id ON portfolios(user_id)`
- `idx_holdings_portfolio_ticker ON holdings(portfolio_id, ticker)` UNIQUE
- `idx_transactions_portfolio_date ON transactions(portfolio_id, transaction_date)`
- `idx_receipts_user_date ON receipts(user_id, scanned_at)`
- `idx_ohlcv_ticker_date ON ohlcv_prices(ticker, date)` UNIQUE
- `idx_refresh_tokens_user ON refresh_tokens(user_id)`
- `idx_refresh_tokens_hash ON refresh_tokens(token_hash)` UNIQUE
- `idx_categories_keywords ON spending_categories USING GIN(merchant_keywords)`
- `idx_conversations_user ON agent_conversations(user_id)`

**`updated_at` trigger** (in the same migration):

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_portfolios_updated_at BEFORE UPDATE ON portfolios
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_holdings_updated_at BEFORE UPDATE ON holdings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

#### `connection.py` (asyncpg pool)

```python
import asyncpg

pool: asyncpg.Pool | None = None

async def init_pool(dsn: str):
    global pool
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)

async def get_conn() -> asyncpg.Connection:
    if pool is None:
        raise RuntimeError("Database pool not initialised")
    return await pool.acquire()

async def release_conn(conn: asyncpg.Connection):
    if pool:
        await pool.release(conn)

async def close_pool():
    global pool
    if pool:
        await pool.close()
        pool = None
```

#### `init_db.py` (runs Alembic migrations on startup)

```python
from alembic.config import Config
from alembic import command

async def run_migrations():
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
```

Called in FastAPI `lifespan` on startup with retry logic (3 attempts, 2s backoff). `command.upgrade` is synchronous — run it via `asyncio.to_thread()` from the lifespan.

---

### Step 3: Auth Module (JWT + Redis + Refresh Token Table + Rate Limiting)

**Round:** 3
**Agent:** general

**Task:** Implement JWT auth with multi-session refresh token rotation, PostgreSQL-backed revocation, Redis blacklisting, and sliding-window rate limiting via slowapi.

**Pattern reference:** LAAD's `backend/src/auth/auth_router.py` — adapted for async + refresh_tokens table.

**Endpoints:**

| Method | Path             | Auth | Rate Limit | Description                                            |
| ------ | ---------------- | ---- | ---------- | ------------------------------------------------------ |
| POST   | `/auth/register` | No   | 20/min     | Create account (email, password, display_name)         |
| POST   | `/auth/login`    | No   | 20/min     | Email + password → access_token + refresh_token        |
| POST   | `/auth/refresh`  | No   | 20/min     | Refresh token → new access + refresh token pair        |
| POST   | `/auth/logout`   | Yes  | 100/min    | Blacklist access token + revoke specific refresh token |
| GET    | `/auth/me`       | Yes  | 100/min    | Return current user info                               |

**Token design:**

- **Access token:** JWT, HS256, 30 min expiry, payload: `{sub: user_id, email: email, exp, iat}`
- **Refresh token:** JWT, HS256, 7 day expiry, payload: `{sub: user_id, token_type: "refresh", jti: uuid, exp, iat}`
  - `jti` (JWT ID) is a unique UUID stored in PostgreSQL. Enables per-session revocation.
- Refresh tokens stored as SHA256(`{jti}:{user_id}`) hash in `refresh_tokens` table
- Access tokens blacklisted in Redis with TTL = remaining expiry

**Multi-session:** Each login creates a new refresh token. All existing tokens for other sessions remain valid. A separate `POST /auth/logout-all` can revoke all sessions.

**Refresh token rotation:** Each `/auth/refresh` call:

1. Validates the current refresh token (JWT decode + hash lookup in DB)
2. Checks the token is not revoked
3. Issues a new access token AND a new refresh token (with new `jti`)
4. Revokes the old refresh token in PostgreSQL (sets `revoked = TRUE`)
5. If the old refresh token was already revoked → the original token was stolen, revoke ALL tokens for that user (force re-login everywhere)

**`POST /login` response body:**

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

Mobile clients store both in `expo-secure-store`. Web clients also get them in the response body (no httponly cookies — mobile cannot use them, and web can store in memory/localStorage).

**`POST /logout`:**

1. Receive the refresh token in the request body: `{"refresh_token": "..."}`
2. Compute SHA256 hash, mark `revoked = TRUE` in `refresh_tokens` table
3. Blacklist the access token in Redis (TTL = remaining expiry)
4. Return 204 No Content

**`POST /auth/refresh`:**

- Accepts `TokenRefreshRequest`: `{"refresh_token": "..."}`
- Returns new `{"access_token", "refresh_token", "token_type", "expires_in"}`

**`dependencies.py`:**

- `get_current_user` — extracts Bearer token from `Authorization: Bearer <token>` header, decodes JWT, checks Redis blacklist, returns user dict. Same pattern as LAAD.
- Redis blacklist check happens on every authenticated request (~1ms overhead).

**Redis client (`cache/redis.py`):**

- `get_redis_client()` — returns Redis client from connection pool
- `blacklist_token(token_jti, ttl_seconds)` — stores jti in Redis with TTL
- `is_token_blacklisted(token_jti)` — checks existence in Redis
- Graceful degradation: if Redis is down, auth still works (no blacklist check, just skip)

**Rate limiting (`middleware/rate_limit.py`):**

- Uses `slowapi` with `Limiter` attached to FastAPI app
- Storage backend: Redis (via `slowapi.RedisBackend`)
- Default limit: `100/minute` (stretch burst to 100, sliding window)
- Login/register endpoint: `20/minute` (stretch burst to 20, sliding window)
- Sliding window implementation: Redis sorted sets via `slowapi`'s `RedisBackend`
- On Redis failure: rate limiting degrades gracefully (no limit applied)

**`schemas.py`:**

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=100)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class LogoutRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    created_at: str
```

**`auth/utils.py`:**

- `hash_password(password) → str` — bcrypt hash with work factor 12
- `verify_password(password, hash) → bool`
- `create_access_token(user_id, email) → str`
- `create_refresh_token(user_id) → tuple[str, str]` — returns `(token, jti)`
- `hash_refresh_token(jti, user_id) → str` — SHA256 for DB storage
- `decode_token(token) → dict` — decode and verify JWT, raise on expiry/invalid

---

### Step 4: Portfolio CRUD

**Round:** 4
**Agent:** general

**Task:** Full CRUD for portfolios, nested under authenticated user.

**Endpoints:**

| Method | Path                         | Description                                            |
| ------ | ---------------------------- | ------------------------------------------------------ |
| GET    | `/portfolios`                | List all portfolios for current user                   |
| POST   | `/portfolios`                | Create portfolio                                       |
| GET    | `/portfolios/{portfolio_id}` | Get portfolio by ID (scoped to user)                   |
| PUT    | `/portfolios/{portfolio_id}` | Update portfolio (name, description)                   |
| DELETE | `/portfolios/{portfolio_id}` | Delete portfolio (cascades to holdings + transactions) |

**Validation rules:**

- Portfolio name: 1–100 chars, required
- Description: optional, max 500 chars
- All operations scoped to `user_id` from JWT — never trust `user_id` from request body
- 404 if portfolio not found OR not owned by user (don't reveal which)

**Async SQL pattern (all endpoints are `async def`, DB calls use asyncpg):**

```python
# Example: list portfolios
async def list_portfolios(user_id: str, conn: asyncpg.Connection):
    rows = await conn.fetch(
        """SELECT id, user_id, name, description, created_at, updated_at
           FROM portfolios WHERE user_id = $1 ORDER BY created_at DESC""",
        user_id,
    )
    return [dict(row) for row in rows]
```

Key difference from `psycopg2`: asyncpg uses `$1`, `$2` parameter placeholders (not `%s`), and all calls are `await conn.fetch()` / `await conn.fetchrow()` / `await conn.execute()`.

---

### Step 5: Holdings CRUD

**Round:** 4
**Agent:** general

**Task:** CRUD for holdings nested under portfolio.

**Endpoints:**

| Method | Path                                               | Description                                  |
| ------ | -------------------------------------------------- | -------------------------------------------- |
| GET    | `/portfolios/{portfolio_id}/holdings`              | List all holdings in portfolio               |
| POST   | `/portfolios/{portfolio_id}/holdings`              | Add holding (ticker, shares, avg cost basis) |
| GET    | `/portfolios/{portfolio_id}/holdings/{holding_id}` | Get holding details                          |
| PUT    | `/portfolios/{portfolio_id}/holdings/{holding_id}` | Update shares / cost basis                   |
| DELETE | `/portfolios/{portfolio_id}/holdings/{holding_id}` | Remove holding                               |

**Validation rules:**

- `ticker`: uppercase, 1–10 chars, validated
- `shares`: positive decimal (allow fractions for fractional shares)
- `average_cost_basis`: positive decimal
- `(portfolio_id, ticker)` unique constraint
- Portfolio ownership verified before any operation

---

### Step 6: Transactions CRUD

**Round:** 4
**Agent:** general

**Task:** CRUD for transactions nested under portfolio.

**Endpoints:**

| Method | Path                                               | Description                                         |
| ------ | -------------------------------------------------- | --------------------------------------------------- |
| GET    | `/portfolios/{portfolio_id}/transactions`          | List transactions (paginated, filterable by ticker) |
| POST   | `/portfolios/{portfolio_id}/transactions`          | Record BUY or SELL transaction                      |
| GET    | `/portfolios/{portfolio_id}/transactions/{txn_id}` | Get transaction details                             |

**Validation rules:**

- `type`: must be `BUY` or `SELL`
- `shares`: positive decimal
- `price_per_share`: positive decimal
- `total_amount` = `shares * price_per_share` (computed server-side, client-provided value validated against this). DB-level CHECK constraint enforces this — any row violating it is rejected at the database level.
- `transaction_date`: must not be in the future (basic sanity check)
- Portfolio ownership verified before any operation
- Transactions are append-only (no DELETE or UPDATE — audit trail)

**Pagination:**

- `?limit=50&offset=0` query params
- Default limit 50, max 100
- Return total count in response header `X-Total-Count`

---

### Step 7: Spending Categories & Merchant Mapping

**Round:** 3
**Agent:** general

**Task:** Seed spending categories, implement merchant → category mapping with keyword lookup + Bedrock fallback.

**`seed.py`** — idempotent seed of default categories:

| Category      | Keywords                                                                                                                                                        | Associated Tickers       |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| Groceries     | tesco, sainsbury, asda, morrisons, waitrose, aldi, lidl, coop, iceland, marks & spencer food                                                                    |                          |
| Dining        | mcdonalds, nando's, zizzi, wagamama, pizza express, prezzo, byron, itsu, wasabi, greggs, subway, kfc, burger king, domino's, costa, starbucks, caffe nero, pret | MCD, YUM, SBUX, DPZ, CMG |
| Transport     | uber, bolt, trainline, national rail, tfl, london underground, bus, shell, bp, tesco petrol, esso                                                               | UBER, TSLA               |
| Utilities     | british gas, edf, eon, octopus, scottish power, sse, npower, severn trent, thames water, vodafone, ee, o2, three, sky, virgin media, bt                         |                          |
| Entertainment | cineworld, odeon, vue, netflix, spotify, disney+, amazon prime, apple tv, now tv, nintendo, xbox, playstation                                                   | NFLX, SPOT, DIS, AMZN    |
| Healthcare    | boots, lloyds pharmacy, superdrug, nhs, dentist, optician, hospital, gp                                                                                         |                          |
| Shopping      | amazon, argos, john lewis, next, debenhams, marks & spencer, primark, h&m, zara, asos, ebay                                                                     | AMZN, EBAY               |
| Travel        | easyjet, ryanair, british airways, jet2, expedia, booking.com, airbnb, hotels.com, trainline                                                                    | EXPE, ABNB, BKNG         |
| Education     | udemy, coursera, skillshare, pluralsight, datacamp, khan academy                                                                                                |                          |

**`merchant_map.py`:**

- `MerchantMatcher` class
- `match(merchant_name: str) -> tuple[str, float]` — returns `(category_name, confidence)`
- Lookup algorithm:
  1. Normalise merchant name: lowercase, strip whitespace, remove "ltd", "limited", "plc"
  2. Keyword match: iterate categories, check if any keyword is a substring of merchant name. If single match → return (category, 0.9). If multiple matches → return highest-priority match.
  3. If no keyword match → fall back to Bedrock
- Bedrock fallback (`_bedrock_classify(merchant_name) -> str`):
  - Uses `boto3` client for `anthropic.claude-3-haiku-20240307-v1:0`
  - Prompt: "Classify this merchant into one of: {comma-separated category names}. Only respond with the category name. Merchant: {merchant_name}"
  - Timeout: 5 seconds
  - If Bedrock is unreachable or returns invalid → return "Uncategorised" with confidence 0.0
- Graceful degradation: if Bedrock call fails (network, auth, timeout), fall back to "Uncategorised" — never block the scan

---

### Step 8: OCR Pipeline (OpenCV Preprocessing + pytesseract)

**Round:** 2
**Agent:** general

**Task:** Implement pytesseract-based OCR pipeline with OpenCV preprocessing, extracting total amount, merchant name, and line items from receipt images.

**`receipts/ocr.py`:**

**`process_receipt(image_bytes: bytes) -> dict`:**

1. Load image bytes → numpy array via OpenCV
2. Preprocess (OpenCV pipeline):
   - Convert to grayscale: `cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)`
   - Denoise: `cv2.fastNlMeansDenoising(gray, h=30)` — reduces sensor noise without blurring edges
   - Adaptive threshold: `cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)` — handles uneven lighting and shadows common on crumpled receipts
   - Optional deskew: `cv2.getRotationMatrix2D` + `cv2.warpAffine` if >2° skew detected
3. Convert processed numpy array back to PIL Image (`Image.fromarray()`) for pytesseract
4. Run pytesseract: `image_to_string` with `--psm 6` (block of text)
5. Run pytesseract: `image_to_data` for bounding box + confidence
6. Extract components:
   - **Total amount:** regex patterns — `Total\s*[£$€]?\s*(\d+\.?\d*)`, `Amount Due\s*[£$€]?\s*(\d+\.?\d*)`, `Grand Total`, etc. Support £ (primary), $, €.
   - **Merchant name:** first non-empty line of OCR output that looks like a merchant (not "RECEIPT", "INVOICE", date patterns, etc.)
   - **Line items:** parse lines containing price patterns, associate with descriptions
   - **Date:** regex for date patterns (DD/MM/YYYY, MM/DD/YYYY, etc.)
7. Return structured result:
   ```json
   {
     "total_amount": 47.99,
     "merchant_name": "Tesco",
     "line_items": [
       { "description": "Milk 2L Semi", "amount": 1.65, "quantity": 1 },
       { "description": "Bread Wholemeal", "amount": 1.2, "quantity": 1 }
     ],
     "date": "2026-06-25",
     "ocr_confidence": 0.87,
     "ocr_raw_text": "...full OCR output..."
   }
   ```

**`parse_total(text: str) -> Decimal | None`:**

- Regex patterns for various receipt formats
- Returns `None` if no total found (receipt may need manual entry)

**`parse_merchant(text: str) -> str | None`:**

- Heuristics: skip lines matching date patterns, "RECEIPT", "INVOICE", "THANK YOU", etc.
- Return the first plausible merchant name line

---

### Step 9: Receipt CRUD + OCR Integration

**Round:** 4
**Agent:** general

**Task:** Full CRUD for receipts + `/receipts/scan` endpoint that runs OCR pipeline and auto-assigns category.

**Endpoints:**

| Method | Path                     | Auth | Description                                |
| ------ | ------------------------ | ---- | ------------------------------------------ |
| GET    | `/receipts`              | Yes  | List receipts for current user (paginated) |
| POST   | `/receipts/scan`         | Yes  | Upload receipt image → OCR → store result  |
| GET    | `/receipts/{receipt_id}` | Yes  | Get receipt details                        |
| PUT    | `/receipts/{receipt_id}` | Yes  | Update receipt (edit OCR mistakes)         |
| DELETE | `/receipts/{receipt_id}` | Yes  | Delete receipt                             |

**`POST /receipts/scan` flow:**

1. Accept multipart upload (field name: `image`, accept: JPEG, PNG). HEIC/HEIF is converted to JPEG on the iOS client side via `expo-image-picker` before upload.
2. Validate file size ≤ 10MB
3. Validate file is an image (check MIME type via magic bytes)
4. Read image bytes → pass to OCR pipeline (Step 8)
5. Pass extracted merchant name to `MerchantMatcher.match()` → get category
6. Store receipt record in `receipts` table with OCR output + category_id
7. Return `ReceiptResponse` with OCR results and assigned category
8. **Critical: image bytes discarded after processing** — never stored on device. Only `ocr_raw_text` and metadata persist.
9. If OCR fails to extract total: return HTTP 422 with `{"detail": "Could not extract total from receipt. Please enter manually.", "ocr_raw_text": "..."}`
10. If OCR fails entirely: return HTTP 422 with detail to retake photo

**File handling:**

- In Phase 1, receipt images are processed and discarded
- If stored (opt-in), image is saved to `backend/data/receipts/{user_id}/{uuid}.jpg` and `receipt_image_s3_key` left null until Phase 5

---

### Step 10: React Native Migration

**Round:** 3
**Agent:** general (TypeScript)

**Task:** Replace all Firebase SDK calls with FastAPI HTTP calls. UI components remain unchanged.

**Current Firebase usage to identify (check `src/services/`, `src/hooks/`, `src/contexts/`):**

- Firebase Auth: email/password login, signup, logout, auth state listener
- Firebase Firestore: CRUD for portfolios, holdings, transactions (if stored in Firestore)
- Firebase Storage: receipt image upload (if currently used)

**New `src/services/api.ts`:**

```typescript
import { getAccessToken, getRefreshToken, saveTokens, clearTokens } from './auth';

const BASE_URL = __DEV__ ? 'http://localhost:8000' : 'https://api.stocklens.app';

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = await getRefreshToken();
  if (!refreshToken) return null;
  try {
    const response = await fetch(`${BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) return null;
    const data = await response.json();
    await saveTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch {
    return null;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let token = await getAccessToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  // If 401, try refreshing token once
  if (response.status === 401) {
    token = await refreshAccessToken();
    if (token) {
      const retry = await fetch(`${BASE_URL}${path}`, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          ...options?.headers,
        },
      });
      if (retry.ok) return retry.json();
    }
    await clearTokens();
    throw new ApiError(401, 'Session expired');
  }
  if (!response.ok) {
    const error = await response.json();
    throw new ApiError(response.status, error.detail);
  }
  return response.json();
}

export const api = {
  // Auth
  register: (email: string, password: string, displayName?: string) =>
    request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),
  login: (email: string, password: string) =>
    request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  logout: (refreshToken: string) =>
    request<void>('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),
  getMe: () => request<UserResponse>('/auth/me'),

  // Portfolios
  getPortfolios: () => request<Portfolio[]>('/portfolios'),
  createPortfolio: (data: CreatePortfolio) =>
    request<Portfolio>('/portfolios', { method: 'POST', body: JSON.stringify(data) }),
  // ... etc
};
```

**Auth token management (`src/services/auth.ts`):**

Store both access and refresh tokens in `expo-secure-store` (already a dependency). The existing app already uses `expo-secure-store` — confirm and reuse.

**New dependency:** `jwt-decode` — lightweight JWT payload decoder (no crypto, pure base64 decode). Used to check `exp` claim without making an HTTP request.

- `saveTokens(accessToken, refreshToken)` → SecureStore
- `getAccessToken()`:
  1. Read access token from SecureStore
  2. Decode JWT via `jwt-decode` to check `exp` timestamp
  3. If expired → call `POST /auth/refresh` with refresh token → save new token pair → return new access token
  4. If still valid → return as-is
- `clearTokens()` → SecureStore delete
- On app launch: check for existing tokens → call `GET /auth/me` to validate → set auth state or clear tokens

**Auth context (`src/contexts/AuthContext.tsx`):**

- Replace Firebase `onAuthStateChanged` listener with:
  - On mount: check if tokens exist in SecureStore → validate via `/auth/me` → set user or null
  - Login: POST `/auth/login` → store tokens → set user
  - Register: POST `/auth/register` → auto-login → store tokens → set user
  - Logout: POST `/auth/logout` → clear tokens → set user null

**Data hooks (`src/hooks/`):**

- `usePortfolios()` → calls `api.getPortfolios()` instead of Firebase Firestore
- `useHoldings(portfolioId)` → calls `api.getHoldings(portfolioId)` instead of Firebase
- `useTransactions(portfolioId)` → calls `api.getTransactions(portfolioId)` instead of Firebase
- `useReceipts()` → calls `api.getReceipts()` instead of Firebase

**Dashboard screen:**

- Remove all Firebase Firestore listeners
- Replace with standard React state + useEffect with API calls
- Pull-to-refresh triggers data re-fetch

**What to preserve:**

- All UI components unchanged
- The existing 78 Jest tests (they test components and hooks — update mocks to point at FastAPI instead of Firebase)
- `expo-secure-store` usage for token storage (already exists)
- `expo-camera` for receipt capture (still used)

**What to remove:**

- Firebase SDK import and initialisation
- `@react-native-firebase/*` packages (check if any are in `package.json`)
- Firebase config files

---

### Step 11: Terraform Provisioning

**Round:** 2
**Agent:** general

**Task:** Terraform modules for VPC, RDS, S3, and ECR. Provisioned early to have real resource URLs for the README/CV.

**Pattern reference:** LAAD's `terraform/modules/` structure — VPC, RDS, and ECR modules directly reusable.

**Terraform directory:** `terraform/` at repo root.

**`provider.tf`:**

- AWS provider, region from variable
- Backend: local (terraform.tfstate in `terraform/`) — S3 backend added in Phase 5

**New module: `modules/vpc/main.tf`** (copied from LAAD):

- VPC: `10.0.0.0/16`
- Two public subnets (for ALB in Phase 5), two private subnets (for RDS + ECS)
- Internet Gateway + NAT Gateway (NAT single-AZ to minimise cost)
- Route tables: public → IGW, private → NAT
- Tags: `Name = "stocklens-{environment}-vpc"`

**`modules/rds/main.tf`:**

- `aws_db_instance`: PostgreSQL 18, `db.t3.micro`, 20GB gp3, `stocklens-db` identifier
- `storage_encrypted = true` (AES-256 at rest)
- `random_password` for master password
- `db_subnet_group_name` → private subnets from VPC module
- Security group: `aws_security_group.rds` — allow PostgreSQL (5432) from VPC CIDR only
- Skip deletion protection for dev (add in Phase 5)
- `skip_final_snapshot = true` for dev (change in Phase 5)

**`modules/s3/main.tf`:**

- `aws_s3_bucket`: `stocklens-{environment}-receipts` — for receipt images (Phase 5+)
- `aws_s3_bucket`: `stocklens-{environment}-drift-reports` — for Evidently reports (Phase 4+)
- `aws_s3_bucket`: `stocklens-{environment}-mlflow-artifacts` — for MLflow artifacts (Phase 3+)
- All buckets: private ACL, server-side encryption (AES256), block public access
- Lifecycle policy: expire noncurrent versions after 30 days

**`modules/ecr/main.tf`:**

- `aws_ecr_repository`: `stocklens-api`
- Image tag mutability: MUTABLE (dev workflow)
- Scan on push: enabled
- Lifecycle: keep 25 most recent images (same as LAAD)

**`modules/secrets/main.tf`** (new — adapted from LAAD's `modules/secrets/`):

Creates 4 secrets in AWS Secrets Manager:

| Secret Name                           | Purpose                           | Value Source                              |
| ------------------------------------- | --------------------------------- | ----------------------------------------- |
| `stocklens/{environment}/jwt-secret`  | JWT signing key (HS256, ≥256-bit) | `random_password` resource                |
| `stocklens/{environment}/db-url`      | Full DATABASE_URL connection str  | Built from RDS endpoint + master password |
| `stocklens/{environment}/bedrock-key` | AWS Bedrock access + secret key   | Variable (provided at apply time)         |
| `stocklens/{environment}/redis-pass`  | Redis AUTH password               | `random_password` resource                |

- Each secret: `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version`
- IAM policy (attached to ECS task role in Phase 5): `secretsmanager:GetSecretValue` scoped to `arn:aws:secretsmanager:*:*:secret:stocklens/${var.environment}/*`
- checkov skip annotations for automatic rotation (manual rotation acceptable for dev)

**`modules/rds/main.tf` update — backup, Multi-AZ, and Secrets Manager integration:**

Add to the existing RDS module:

- `backup_retention_period = 7` (7-day automated backups with PITR)
- `backup_window = "03:00-04:00"` (UTC)
- `multi_az = var.environment == "prod" ? true : false` (enable Multi-AZ for prod)
- `copy_tags_to_snapshot = true`
- Master password sourced from `random_password` (local) in dev, from Secrets Manager `data.aws_secretsmanager_secret_version.db_master` in prod
- Output: `rds_endpoint` (used by secrets module to build DATABASE_URL)

**IaC security scanning (`checkov.yml`):**

```yaml
# terraform/checkov.yml — IaC security policy
compact: true
framework: terraform
skip-check:
  - CKV_AWS_149 # Secrets Manager KMS key (dev)
  - CKV2_AWS_57 # Secrets Manager rotation (dev)
  - CKV_AWS_117 # VPC flow logs (added in Tier 2)
```

- CI runs `checkov --config-file checkov.yml -d .` and `tfsec .` on every PR touching `terraform/`
- Critical/high findings block the PR from merging

**`main.tf`:**

```hcl
module "vpc"     { source = "./modules/vpc"     ... }
module "secrets" { source = "./modules/secrets" ... }
module "rds"     { source = "./modules/rds"     vpc_id = module.vpc.vpc_id private_subnet_ids = module.vpc.private_subnet_ids ... }
module "s3"      { source = "./modules/s3"      ... }
module "ecr"     { source = "./modules/ecr"     ... }
```

**Phase 5 preparation — module stubs created now, provisioned later:**

To keep Phase 1 lean, the `waf/` and `monitoring/` module directories are created with skeleton files now (so the Terraform directory structure is ready), but they are **not called from `main.tf`** until Phase 5.

| Module                       | Phase | What it provisions                                                                                                                                                                                            | CV narrative                                                           |
| ---------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `modules/waf/main.tf`        | 5     | `aws_wafv2_web_acl` with rate-based rule (200 req/min per IP), SQL injection + XSS match statements, associated with ALB                                                                                      | "WAF rate limiting + SQLi/XSS protection on ALB"                       |
| `modules/monitoring/main.tf` | 5     | `aws_cloudwatch_dashboard` (p50/p95/p99 latency, error rate, RDS connections, ECS CPU/memory), `aws_budgets_budget` ($50 monthly), `aws_cloudwatch_metric_alarm` for ECS + RDS health, Cost Anomaly Detection | "CloudWatch dashboards + AWS Budgets with cost anomaly detection"      |
| ECS Service Auto Scaling     | 5     | `aws_appautoscaling_target` + `aws_appautoscaling_policy` for ECS service — target tracking on CPU (75%) + request count per target (1000/ALB)                                                                | "ECS Service Auto Scaling with target tracking on CPU + request count" |

**Usage:**

```bash
cd terraform
terraform init
terraform plan -var="environment=dev"
# IaC security scan (separate CI step):
pip install checkov tfsec && checkov --config-file checkov.yml -d . && tfsec .
terraform apply -var="environment=dev"
# Outputs: VPC ID, RDS endpoint, S3 bucket names, ECR repository URL, Secret ARNs
```

---

### Step 12: Test Suite

**Round:** 5
**Agent:** general / code-reviewer

**Task:** Write 60–80 pytest tests covering all Phase 1 functionality.

**Test infrastructure (`tests/conftest.py`):**

Uses asyncpg with per-test transaction rollback for full isolation:

```python
import asyncpg
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database.connection import init_pool, close_pool

@pytest.fixture
async def test_db():
    """Create a fresh connection to postgres_test, start a transaction,
    rollback after the test. No state leaks between tests."""
    conn = await asyncpg.connect(settings.TEST_DATABASE_URL)
    await conn.execute("BEGIN")
    yield conn
    await conn.execute("ROLLBACK")
    await conn.close()

@pytest.fixture
async def client():
    """Async HTTP client against the FastAPI app (no server needed)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def auth_headers(client):
    """Register a test user, login, return auth header dict."""
    await client.post("/auth/register", json={
        "email": "test@test.com", "password": "password123"
    })
    resp = await client.post("/auth/login", json={
        "email": "test@test.com", "password": "password123"
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
async def test_portfolio(client, auth_headers):
    """Create a portfolio for the authenticated test user."""
    resp = await client.post("/portfolios",
        json={"name": "Test Portfolio"},
        headers=auth_headers,
    )
    return resp.json()
```

Note: Redis calls are mocked via `pytest-mock` for unit tests. Integration tests use the real Redis container.

**Test categories and targets:**

| Test File              | Tests                                                                                                                                                                   | Count |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| `test_auth.py`         | Register, login, refresh (rotation), logout (revoke specific token), me, invalid credentials, duplicate email, expired token, blacklisted token, stolen token detection | 14–18 |
| `test_portfolios.py`   | Create, list, get, update, delete, 404 for wrong user, validation errors                                                                                                | 10–12 |
| `test_holdings.py`     | CRUD under portfolio, duplicate ticker validation, portfolio ownership check, delete cascade                                                                            | 10–12 |
| `test_transactions.py` | Create BUY/SELL, list with pagination, validation (future date, negative shares, total_amount mismatch), portfolio ownership                                            | 10–12 |
| `test_receipts.py`     | Create receipt, list, get, update, delete, scan endpoint (multipart upload mock), ownership check                                                                       | 10–12 |
| `test_ocr.py`          | Total regex patterns (£, $, "Grand Total", "Amount Due"), merchant name extraction, line item parsing, OpenCV preprocessing, empty image, low-contrast image            | 10–12 |
| `test_categories.py`   | Seed data verification, keyword matching, Bedrock fallback mock, unknown merchant fallback                                                                              | 6–8   |
| `test_cache.py`        | Redis blacklist set/get, TTL, graceful degradation when Redis unavailable                                                                                               | 4–6   |
| `test_rate_limit.py`   | Sliding window enforcement, login rate limit exceeded, default rate limit reset                                                                                         | 4–6   |

**Total target: 78–95 tests.**

**Test patterns:**

```python
# Async HTTP test example (all tests async)
async def test_create_portfolio(client, auth_headers):
    response = await client.post(
        "/portfolios",
        json={"name": "My Portfolio", "description": "Test"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Portfolio"
    assert "id" in data

# OCR test example (sync — pure function)
def test_parse_total_pound():
    from src.receipts.ocr import parse_total
    assert parse_total("Total £47.99") == 47.99

def test_parse_total_grand_total():
    from src.receipts.ocr import parse_total
    assert parse_total("Grand Total: $123.45") == 123.45
```

**Coverage target:** ≥80% for `backend/src/` (excluding `tests/`).

---

## Definition of Done

Phase 1 is complete when ALL of the following are true:

### Functional

- [ ] Docker Compose starts all services: `docker compose up -d` succeeds with healthy services
- [ ] User can register, login, refresh token, and logout via API
- [ ] Authenticated user can CRUD portfolios
- [ ] Authenticated user can CRUD holdings within a portfolio
- [ ] Authenticated user can create and list transactions within a portfolio
- [ ] Receipt image upload → OCR extracts total, merchant, line items
- [ ] Merchant name → spending category mapping works (keyword match + Bedrock fallback)
- [ ] All receipt CRUD operations work, scoped to the authenticated user
- [ ] React Native app builds and runs against FastAPI backend (not Firebase)
- [ ] User can log in via the app (email/password → JWT → SecureStore)
- [ ] User can scan a receipt via the app camera → OCR result stored
- [ ] User can view their portfolios, holdings, and transactions in the app

### Non-Functional

- [ ] All 70–85 pytest tests pass
- [ ] All existing 78 Jest tests pass (after updating mocks)
- [ ] Python test coverage ≥80%
- [ ] `ruff check .` passes with zero errors
- [ ] ESLint passes with zero errors
- [ ] TypeScript type check passes: `npx tsc --noEmit`
- [ ] Terraform plan succeeds: `terraform plan -var="environment=dev"` exits 0
- [ ] IaC security scan passes: `checkov --config-file checkov.yml -d terraform/` and `tfsec terraform/` — zero critical/high findings
- [ ] Secrets Manager secrets created: `aws secretsmanager list-secrets` shows stocklens secrets
- [ ] No Firebase SDK calls remain in the React Native app
- [ ] Receipt images are never stored on device after processing
- [ ] Passwords are bcrypt-hashed with work factor ≥12, never stored in plaintext
- [ ] JWT tokens stored in mobile SecureStore (access + refresh), sent via Authorization header
- [ ] Refresh token rotation active: each `/auth/refresh` invalidates the old refresh token
- [ ] Logout revokes the specific refresh token in PostgreSQL (not just blacklists access token)
- [ ] Rate limiting active (slowapi + Redis sliding window): 20/min for auth, 100/min for others

### Documentation

- [ ] `README.md` updated with setup instructions for Phase 1
- [ ] `.env.example` contains all required environment variables with sensible defaults
- [ ] `docker-compose.yml` includes all services with health checks
- [ ] All FastAPI endpoints have docstrings (auto-documented in `/docs`)
- [ ] Alembic migrations can be run: `alembic upgrade head` exits 0

---

## Verification Checklist

### Local Dev Environment

```bash
# Start all services
make up

# Check health
curl http://localhost:8000/health
# → {"status": "ok"}

# Check docs are live
open http://localhost:8000/docs

# Run tests
make test

# Check coverage
docker compose run --rm pytest --cov=src --cov-report=term-missing
```

### Auth Flow Verification

```bash
# Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com", "password": "password123", "display_name": "Test"}'

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com", "password": "password123"}'
# → {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 1800}

# Refresh token
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "..."}'
# → {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 1800}

# Use token
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <access_token>"
# → {"email": "test@test.com", "id": "...", "display_name": "Test", "created_at": "..."}

# Logout (must send refresh_token to revoke it)
curl -X POST http://localhost:8000/auth/logout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"refresh_token": "..."}'
# → 204 No Content
```

### OCR Flow Verification

```bash
# Scan a receipt (test image at backend/data/test_receipt.jpg)
curl -X POST http://localhost:8000/receipts/scan \
  -H "Authorization: Bearer <token>" \
  -F "image=@backend/data/test_receipt.jpg"
# → {"total_amount": 47.99, "merchant_name": "Tesco", "category": "Groceries", ...}
```

### React Native Verification

```bash
# App starts
npx expo start

# Auth flow works: register → login → dashboard loads with data
# Receipt scan flow works: camera → upload → result displayed
# All Firebase console errors gone (check Metro bundler)
```

---

## Appendix A: Key LAAD Pattern References

These files in `/Users/ahmedikram/GitHub Repos/laad` provide direct reference implementations:

| Pattern                            | LAAD File                                                                               |
| ---------------------------------- | --------------------------------------------------------------------------------------- |
| Docker Compose structure           | `docker-compose.yml`                                                                    |
| PostgreSQL connection pool (async) | `backend/src/database/connection.py` — adapt for asyncpg                                |
| DB init with Alembic               | LAAD uses raw SQL; adapt to Alembic async pattern                                       |
| JWT auth router                    | `backend/src/auth/auth_router.py` — structure, adapt for async + refresh_tokens table   |
| Redis client                       | `backend/src/cache/redis_client.py`                                                     |
| FastAPI main with lifespan         | `backend/src/api/server.py`                                                             |
| Backend Dockerfile                 | `backend/Dockerfile`                                                                    |
| Terraform VPC module               | `terraform/modules/vpc/main.tf` — directly reusable                                     |
| Terraform RDS module               | `terraform/modules/rds/main.tf` — directly reusable                                     |
| Terraform ECR module               | `terraform/modules/ecr/main.tf` — directly reusable                                     |
| Terraform root module              | `terraform/main.tf` — structure                                                         |
| MLflow custom image                | `mlflow/Dockerfile`                                                                     |
| Secrets Manager module             | `terraform/modules/secrets/main.tf` — 7+ secrets pattern, adapt for 4 StockLens secrets |
| Monitoring / CloudWatch module     | `terraform/modules/monitoring/main.tf` — metric alarms for RDS, ECS, SageMaker          |
| IAM least-privilege policies       | `terraform/modules/iam/main.tf` — secrets read + CloudWatch write policies              |

## Appendix B: Security Requirements

- [ ] Passwords: bcrypt with work factor ≥12
- [ ] JWT: HS256 with minimum 256-bit secret key
- [ ] Refresh tokens: stored as SHA256 hash in PostgreSQL, per-session (multi-session support)
- [ ] Refresh token rotation: each `/auth/refresh` issues new pair, revokes old token
- [ ] Stolen token detection: if a revoked refresh token is reused, all sessions for that user are invalidated
- [ ] Logout: revokes the specific refresh token in PostgreSQL + blacklists access token in Redis
- [ ] Receipt images: processed in memory, discarded immediately
- [ ] All database connections use parameterised queries with `$1`, `$2` placeholders (asyncpg)
- [ ] Redis blacklist checked on every authenticated request
- [ ] Rate limiting: sliding window via slowapi + Redis — 20 requests/min for `/auth/login` + `/auth/register`, 100/min for other endpoints
- [ ] CORS: restricted to `http://localhost:8081` in dev (Expo dev server)
- [ ] Secrets: all production secrets stored in AWS Secrets Manager, never in `.env` files or code
- [ ] IaC security: checkov + tfsec run in CI, critical/high findings block PRs
- [ ] RDS: `storage_encrypted = true` (AES-256 at volume level), security group restricted to VPC CIDR
