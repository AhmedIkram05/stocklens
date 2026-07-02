# StockLens — Master Implementation Plan

> **Status:** Draft
> **Last updated:** 2026-06-26
> **Target:** Full-stack FinTech app — receipt OCR → investment analysis → portfolio tracking → ML forecasting → conversational agent

---

## Table of Contents

1. [Purpose & Goals](#purpose--goals)
2. [Architecture Overview](#architecture-overview)
3. [Technology Stack](#technology-stack)
4. [Database Schema](#database-schema)
5. [Phase Overview](#phase-overview)
6. [Shared Conventions](#shared-conventions)
7. [CI/CD & Infrastructure](#cicd--infrastructure)
8. [CV Narrative](#cv-narrative)

---

## Purpose & Goals

### Problem

Physical receipts contain spending data that could inform investment decisions, but no consumer tool bridges the gap between "what I spent" and "where I should invest."

### Solution

StockLens scans receipts via OCR, maps merchants to stock tickers, tracks portfolio performance against market benchmarks, forecasts price direction with an LSTM, and answers natural-language questions about your finances via a ReAct agent.

### Principles

1. **No Firebase.** The entire backend is FastAPI + PostgreSQL. Firebase is eliminated completely.
2. **No Node.js middleware.** The backend is Python end-to-end.
3. **RDS storage encryption (AES-256).** EBS volume-level encryption for all data at rest. Application-layer encryption is not required — the backend threat model (server in owned AWS account) differs from the original mobile-first app (device theft risk).
4. **Secrets are never hardcoded.** All secrets (JWT key, database credentials, API keys) stored in AWS Secrets Manager with least-privilege IAM policies. No `.env` files in production.
5. **Everything runs locally in Docker Compose for development.** AWS infra provisioned via Terraform for production/staging.
6. **Agents write the code.** These documents are designed for AI coding agents to execute with minimal ambiguity.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    React Native (Expo)                    │
│  Screens → Hooks → API Client → FastAPI HTTP             │
│  Biometric auth (Face ID / Touch ID)                      │
│  Secure Store for JWT tokens                              │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────┐
│                    FastAPI Backend                        │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌────────┐  ┌────────┐  │
│  │ Auth │  │ CRUD │  │ OCR  │  │ Market │  │ Agent  │  │
│  │ JWT  │  │ Port │  │ Py  │  │ Data   │  │ Lang   │  │
│  │      │  │folios│  │tess  │  │yfinance│  │Chain   │  │
│  └──────┘  └──────┘  └──────┘  └────────┘  └────────┘  │
│                          │                               │
│  ┌───────────────────────┴───────────────────────────┐  │
│  │  Redis (JWT blacklist, rate limit, cache)         │  │
│  └───────────────────────┬───────────────────────────┘  │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                    PostgreSQL                             │
│  users, refresh_tokens, portfolios, holdings,             │
│  transactions, receipts, spending_categories,              │
│  ohlcv_prices, model_registry, agent_conversations        │
└─────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    AWS (Terraform)                            │
│  RDS (PostgreSQL) │ S3 (receipts, drift reports) │ ECR       │
│  Secrets Manager │ CloudWatch (logs, metrics, dashboards)    │
│  SageMaker (LSTM endpoint) │ ECS Fargate (API) │ ALB │ WAF  │
└──────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    MLOps (Phase 4)                        │
│  Airflow (EC2) → weekly retrain → MLflow → champion     │
│  Evidently drift reports → S3                            │
└─────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer               | Technology                                | Version / Notes                                                                   |
| ------------------- | ----------------------------------------- | --------------------------------------------------------------------------------- |
| Mobile              | React Native (Expo)                       | SDK 56, RN 0.85, React 19.2                                                       |
| Mobile language     | TypeScript                                | 5.6+, strict mode                                                                 |
| Backend             | FastAPI                                   | 0.138.x                                                                           |
| Backend language    | Python                                    | 3.14                                                                              |
| Async runtime       | asyncpg                                   | 0.30.x (connection pool for PostgreSQL)                                           |
| Package manager     | uv                                        | 0.11.x (Rust-based, fast resolver)                                                |
| Database            | PostgreSQL                                | 18 (local Docker `18-alpine` + RDS)                                               |
| Cache               | Redis                                     | 8.8 (`8.8-alpine`)                                                                |
| Auth                | JWT (Authorization header)                | HS256, bcrypt 5.x                                                                 |
| Rate limiting       | slowapi                                   | Sliding window via Redis                                                          |
| Migration tool      | Alembic                                   | SQL-based migrations via `op.execute()` (no ORM dependency)                       |
| OCR                 | pytesseract                               | 0.3.13                                                                            |
| OCR preprocessing   | opencv-python-headless                    | 4.10.x (adaptive threshold, denoise)                                              |
| OCR LLM fallback    | AWS Bedrock Claude Haiku                  | Via langchain-aws / boto3 1.43+                                                   |
| Market data         | yfinance                                  | Free Yahoo Finance API                                                            |
| ML framework        | PyTorch                                   | 2.12.x                                                                            |
| Experiment tracking | MLflow                                    | 3.14.x (custom Docker image)                                                      |
| Model registry      | MLflow Model Registry                     | Alias-based (champion/challenger)                                                 |
| Orchestration       | Airflow                                   | Docker Compose on EC2 t3.small                                                    |
| Drift detection     | Evidently AI                              | HTML reports → S3                                                                 |
| IaC                 | Terraform                                 | 1.15.x, AWS provider, IaC scanning (checkov + tfsec)                              |
| CI/CD               | GitHub Actions                            | OIDC federation, ruff → pytest → IaC scan → build → deploy                        |
| Secrets management  | AWS Secrets Manager                       | 4+ secrets: JWT key, DB URL, Bedrock key, Redis password                          |
| Observability       | structlog + CloudWatch                    | Structured JSON logging, p50/p95/p99 dashboards, metric alarms                    |
| IaC security        | checkov + tfsec                           | 40+ rules enforced in CI (pre-apply)                                              |
| WAF                 | AWS WAF                                   | Rate-based rules (200/min per IP), SQL injection + XSS protection attached to ALB |
| Cost management     | AWS Budgets + Cost Anomaly Detection      | $50 monthly budget alert, anomaly detection on RDS + ECS                          |
| Container scaling   | ECS Service Auto Scaling                  | Target tracking on CPU + request count per target                                 |
| Agent framework     | LangChain                                 | 1.3.x, ReAct with 5 tools                                                         |
| Container runtime   | Docker Compose (dev) / ECS Fargate (prod) |                                                                                   |

> ⚠️ **Version audit (2026-06-26):** All versions above verified against current PyPI/GitHub releases. Python 3.14.6 is latest stable (released June 10). Expo SDK 56 shipped May 21 with RN 0.85. PostgreSQL 18.4 is latest stable (19 beta 1 out June 4). Redis 8.8.0 GA released May 25. MLflow 3.14.0 released June 17. Re-verify before executing each phase.

---

## Database Schema

> Designed up front — all six phases share this schema. All changes managed via Alembic migrations (numbered, reversible). See [Alembic migration guide](PHASE1_IMPLEMENTATION.md#step-2-database-schema--initialisation).

### Entity-Relationship Summary

```
users 1──N portfolios 1──N holdings
users 1──N receipts
users 1──N transactions
holdings N──1 tickers (implicit, via ohlcv_prices)
receipts N──1 spending_categories
ohlcv_prices N──1 tickers (implicit, via ticker column)
```

### Table: `users`

| Column        | Type         | Constraints                   |
| ------------- | ------------ | ----------------------------- |
| id            | UUID         | PK, default gen_random_uuid() |
| email         | VARCHAR(255) | NOT NULL, UNIQUE              |
| password_hash | VARCHAR(255) | NOT NULL                      |
| display_name  | VARCHAR(100) |                               |
| created_at    | TIMESTAMPTZ  | NOT NULL, DEFAULT NOW()       |
| updated_at    | TIMESTAMPTZ  | NOT NULL, DEFAULT NOW()       |

### Table: `refresh_tokens`

| Column     | Type        | Constraints                                |
| ---------- | ----------- | ------------------------------------------ |
| id         | UUID        | PK, default gen_random_uuid()              |
| user_id    | UUID        | NOT NULL, FK → users(id) ON DELETE CASCADE |
| token_hash | VARCHAR(64) | NOT NULL                                   |
| expires_at | TIMESTAMPTZ | NOT NULL                                   |
| revoked    | BOOLEAN     | NOT NULL, DEFAULT FALSE                    |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW()                    |

Index: `idx_refresh_tokens_user ON refresh_tokens(user_id)`
Index: `idx_refresh_tokens_hash ON refresh_tokens(token_hash)` (unique, for lookup)

### Table: `portfolios`

| Column      | Type         | Constraints                                |
| ----------- | ------------ | ------------------------------------------ |
| id          | UUID         | PK, default gen_random_uuid()              |
| user_id     | UUID         | NOT NULL, FK → users(id) ON DELETE CASCADE |
| name        | VARCHAR(100) | NOT NULL                                   |
| description | TEXT         |                                            |
| created_at  | TIMESTAMPTZ  | NOT NULL, DEFAULT NOW()                    |
| updated_at  | TIMESTAMPTZ  | NOT NULL, DEFAULT NOW()                    |

Index: `idx_portfolios_user_id ON portfolios(user_id)`

### Table: `holdings`

| Column             | Type           | Constraints                                     |
| ------------------ | -------------- | ----------------------------------------------- |
| id                 | UUID           | PK, default gen_random_uuid()                   |
| portfolio_id       | UUID           | NOT NULL, FK → portfolios(id) ON DELETE CASCADE |
| ticker             | VARCHAR(10)    | NOT NULL                                        |
| shares             | DECIMAL(18, 6) | NOT NULL                                        |
| average_cost_basis | DECIMAL(12, 4) | Per-share average cost                          |
| created_at         | TIMESTAMPTZ    | NOT NULL, DEFAULT NOW()                         |
| updated_at         | TIMESTAMPTZ    | NOT NULL, DEFAULT NOW()                         |

Index: `idx_holdings_portfolio_ticker ON holdings(portfolio_id, ticker)` UNIQUE

### Table: `transactions`

| Column           | Type           | Constraints                                             |
| ---------------- | -------------- | ------------------------------------------------------- |
| id               | UUID           | PK, default gen_random_uuid()                           |
| portfolio_id     | UUID           | NOT NULL, FK → portfolios(id) ON DELETE CASCADE         |
| ticker           | VARCHAR(10)    | NOT NULL                                                |
| type             | VARCHAR(4)     | NOT NULL, CHECK (type IN ('BUY', 'SELL'))               |
| shares           | DECIMAL(18, 6) | NOT NULL                                                |
| price_per_share  | DECIMAL(12, 4) | NOT NULL                                                |
| total_amount     | DECIMAL(24, 6) | NOT NULL, CHECK (total_amount = shares price_per_share) |
| transaction_date | DATE           | NOT NULL                                                |
| notes            | TEXT           |                                                         |
| created_at       | TIMESTAMPTZ    | NOT NULL, DEFAULT NOW()                                 |

Index: `idx_transactions_portfolio_date ON transactions(portfolio_id, transaction_date)`

### Table: `receipts`

| Column               | Type           | Constraints                                |
| -------------------- | -------------- | ------------------------------------------ |
| id                   | UUID           | PK, default gen_random_uuid()              |
| user_id              | UUID           | NOT NULL, FK → users(id) ON DELETE CASCADE |
| total_amount         | DECIMAL(10, 2) | NOT NULL                                   |
| merchant_name        | VARCHAR(255)   |                                            |
| category_id          | UUID           | FK → spending_categories(id)               |
| ocr_raw_text         | TEXT           | Original OCR output before parsing         |
| ocr_confidence       | REAL           | Overall confidence score 0–1               |
| line_items           | JSONB          | Array of {description, amount, quantity}   |
| receipt_image_s3_key | VARCHAR(500)   | S3 object key if stored                    |
| scanned_at           | TIMESTAMPTZ    | NOT NULL                                   |
| created_at           | TIMESTAMPTZ    | NOT NULL, DEFAULT NOW()                    |

Index: `idx_receipts_user_date ON receipts(user_id, scanned_at)`
Note: receipt images are discarded after processing unless explicitly opted in.

### Table: `spending_categories`

| Column             | Type         | Constraints                             |
| ------------------ | ------------ | --------------------------------------- |
| id                 | UUID         | PK, default gen_random_uuid()           |
| name               | VARCHAR(50)  | NOT NULL, UNIQUE                        |
| description        | VARCHAR(255) |                                         |
| merchant_keywords  | JSONB        | Array of keywords for auto-matching     |
| associated_tickers | JSONB        | Array of tickers for investment mapping |

Index: `idx_categories_keywords ON spending_categories USING GIN(merchant_keywords)` — enables efficient keyword lookups for merchant mapping.

Seed data: Groceries, Dining, Transport, Utilities, Entertainment, Healthcare, Shopping, Travel, Education, Uncategorised.

### Table: `ohlcv_prices`

| Column         | Type           | Constraints |
| -------------- | -------------- | ----------- |
| id             | BIGSERIAL      | PK          |
| ticker         | VARCHAR(10)    | NOT NULL    |
| date           | DATE           | NOT NULL    |
| open           | DECIMAL(12, 4) |             |
| high           | DECIMAL(12, 4) |             |
| low            | DECIMAL(12, 4) |             |
| close          | DECIMAL(12, 4) |             |
| adjusted_close | DECIMAL(12, 4) |             |
| volume         | BIGINT         |             |

Index: `idx_ohlcv_ticker_date ON ohlcv_prices(ticker, date)` UNIQUE

### Table: `model_registry` (Phase 3+)

| Column               | Type         | Constraints                   |
| -------------------- | ------------ | ----------------------------- |
| id                   | BIGSERIAL    | PK                            |
| ticker               | VARCHAR(10)  |                               |
| mlflow_run_id        | VARCHAR(100) |                               |
| model_version        | VARCHAR(20)  |                               |
| alias                | VARCHAR(20)  | e.g. 'champion', 'production' |
| directional_accuracy | REAL         |                               |
| per_class_f1         | JSONB        |                               |
| simulated_sharpe     | REAL         |                               |
| trained_at           | TIMESTAMPTZ  | NOT NULL, DEFAULT NOW()       |

Index: `idx_conversations_user ON agent_conversations(user_id)`

### Note: `updated_at` columns

Tables with `updated_at` use a database trigger to auto-update on modification:

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Applied to `users`, `portfolios`, `holdings` via `CREATE TRIGGER ... BEFORE UPDATE`.

### Table: `agent_conversations` (Phase 6)

| Column          | Type        | Constraints                                |
| --------------- | ----------- | ------------------------------------------ |
| id              | BIGSERIAL   | PK                                         |
| user_id         | UUID        | NOT NULL, FK → users(id) ON DELETE CASCADE |
| message         | TEXT        | NOT NULL                                   |
| response        | TEXT        | NOT NULL                                   |
| tools_used      | JSONB       | Array of tool names called                 |
| reasoning_steps | JSONB       | Array of reasoning traces                  |
| created_at      | TIMESTAMPTZ | NOT NULL, DEFAULT NOW()                    |

---

## Phase Overview

### Phase 1 — Backend Foundation + Auth + OCR Migration

**Goal:** Eliminate Firebase and Node.js. FastAPI + PostgreSQL is the single backend. All existing functionality ported and improved.

**Key deliverables:**

- Docker Compose: FastAPI + PostgreSQL + Redis
- JWT auth with access + refresh tokens (hardware-backed SecureStore on mobile, not httponly cookies)
- Multi-session refresh token rotation with PostgreSQL-backed revocation
- Full CRUD: portfolios, holdings, transactions
- OCR pipeline: pytesseract (OpenCV preprocessing) + merchant keyword mapping + Bedrock Claude Haiku fallback
- Pytest suite: 70–85 tests
- Terraform: VPC, RDS + S3 + ECR + Secrets Manager (provisioned, but dev uses Docker Compose)
- React Native: swap Firebase SDK calls for FastAPI HTTP calls
- Alembic: declarative migration framework for all schema changes across 6 phases
- Structured JSON logging via structlog (stdout, collected by CloudWatch in production)

**Dependencies:** None (greenfield backend)

[→ Phase 1 Detailed Implementation Plan](PHASE1_IMPLEMENTATION.md)

---

### Phase 2 — Market Data Layer

**Goal:** Replace CAGR calculation with real OHLCV pipeline. Proper portfolio performance analytics.

**Key deliverables:**

- yfinance integration with PostgreSQL caching (`ohlcv_prices`)
- Time-weighted return (TWR) calculation
- Unrealised P&L per holding
- Benchmark comparison (SPY, QQQ)
- FastAPI endpoints: `/market/ohlcv/{ticker}`, `/market/quote/{ticker}`, `/portfolio/performance/{portfolio_id}`, `/portfolio/benchmark/{portfolio_id}`
- Pytest tests: data fetch, caching, TWR edge cases

**Depends on:** Phase 1 (schema, auth, portfolio CRUD)

---

### Phase 3 — PyTorch LSTM

**Goal:** Train directional LSTM, log everything to MLflow on AWS, register champion model.

**Key deliverables:**

- Feature engineering (log returns, moving averages, RSI, MACD, volatility)
- Time-series split (70/15/15, chronological, no shuffle)
- LSTM architecture: 30-day sequence → 2-layer LSTM (hidden 128, dropout 0.3) → softmax (3 classes)
- Training: Adam, cross-entropy, early stopping (patience 10)
- Evaluation: directional accuracy, per-class F1, simulated Sharpe ratio
- MLflow: hyperparams, loss curves, confusion matrix, metrics, model artifact
- Train on ≥50 liquid S&P 500 components + portfolio tickers
- Full frontend integration including replacing old stale code with new LSTM calculated predicted returns and updating other stale or non-existent features with Pytorch LSTM predicted returns

**Depends on:** Phase 2 (needs OHLCV data in PostgreSQL)

---

### Phase 4 — MLOps (Airflow + Evidently)

**Goal:** Automated weekly retraining + drift detection with S3-linked reports.

**Key deliverables:**

- Airflow DAG (weekly Docker Compose on EC2 t3.medium): fetch new OHLCV → retrain LSTM → log to MLflow → compare challenger vs champion → promote if >2pp accuracy improvement
- Evidently data drift + prediction drift reports → HTML → S3 (public-read)
- Alert if JS divergence > 0.3 on any feature

**Depends on:** Phase 3 (trained model to retrain)

---

### Phase 5 — FastAPI Serving + Full AWS Deployment

**Goal:** Production deployment with Terraform, OIDC CI/CD, and SageMaker. Full observability, secrets management, and IaC security.

**Key deliverables:**

- `/predict` endpoint: loads champion LSTM from MLflow, cached in Redis (6h TTL)
- SageMaker serverless inference as optional serving path
- Terraform: ECS Fargate, ALB + WAF, ACM, IAM (least privilege), CloudWatch log groups + metric alarms — VPC already provisioned in Phase 1
- **ECS Service Auto Scaling:** target tracking on CPU + request count per target. Handles traffic spikes without manual scaling.
- **WAF:** rate-based rules (200 req/min per IP), SQL injection + XSS protection on ALB. FinTech security posture.
- **AWS Budgets + Cost Anomaly Detection:** monthly budget alert at $50, anomaly detection on RDS + ECS spend. Cost-aware operations.
- Secrets Manager: production-grade secrets injected into ECS task definition (DATABASE_URL, JWT_SECRET_KEY, BEDROCK_API_KEY, REDIS_PASSWORD). No `.env` files in production.
- CloudWatch dashboard: p50/p95/p99 latency, error rate, RDS connections, ECS CPU/memory
- GitHub Actions CI/CD: ruff → pytest → checkov + tfsec → docker build → ECR → ECS deploy (OIDC auth)

**Depends on:** Phase 3 (model to serve). Terraform provisioning can begin in parallel with Phase 3.

---

### Phase 6 — LangChain Tool-Use Agent

**Goal:** ReAct agent with five tools deployed as a FastAPI endpoint, integrated into React Native.

**Key deliverables:**

- Five tools: `get_lstm_forecast`, `get_market_data`, `get_portfolio_summary`, `get_spending_analysis`, `compare_to_benchmark`
- LangChain ReAct agent with tool descriptions as system prompt
- FastAPI `/agent/chat` endpoint
- 15-question golden evaluation set
- React Native conversational UI screen
- Evidently integration again but for LLM response quality

**Depends on:** Phase 5 (agent calls serving endpoint)

---

## Shared Conventions

### Code Style (Python)

- Ruff for linting (imported rules: pyflakes, pycodestyle, isort)
- Type hints on all function signatures
- Pydantic models for all request/response schemas
- Exception hierarchy: HTTPException with descriptive detail strings

### Code Style (TypeScript)

- Existing ESLint flat config (`eslint.config.js`) extending `eslint-config-universe/flat/native`
- Prettier (single quotes, trailing commas, 100 print width)
- Services injected via hooks (never call APIs directly from screens)

### Testing

- **Python:** pytest + httpx (async HTTP tests via `httpx.AsyncClient`) + pytest-mock + pytest-cov + pytest-asyncio
- **Async DB tests:** asyncpg connection pool with per-test transaction rollback (fast, isolated)
- **TypeScript:** Jest (existing 78 tests preserved during migration, then updated)
- **Coverage target:** ≥80% for new Python code
- **Test types:** unit (isolated logic), integration (DB + API), snapshot (RN components)

### Documentation

- Every FastAPI endpoint has a docstring
- Pydantic models used as OpenAPI schema (auto-documented by FastAPI)
- Inline comments only for non-obvious logic
- README updated after each phase

---

## CI/CD & Infrastructure

### Phase 1–4 (Development)

- Docker Compose for local development
- GitHub Actions: lint + typecheck + unit tests
- IaC security scan (checkov + tfsec) runs on every PR touching `terraform/`
- Terraform: plan-only in PRs (no apply)

### Phase 5+ (Production)

- GitHub Actions CI/CD: ruff → pytest → checkov + tfsec → docker build → push to ECR → ECS Fargate rolling deploy
- OIDC federation — no static AWS credentials
- Deployment blocked if any pytest fails or IaC scan finds critical/high findings
- Secrets Manager: ECS task definition injects secrets as environment variables at container start (DevSync pattern via `jq` or Terraform `aws_ecs_task_definition` secrets block)
- CloudWatch: structured JSON logs from structlog collected via `awslogs` driver, custom dashboard with p50/p95/p99 latency, RDS connections, ECS CPU/memory, error rate
- AWS Budgets alarm at $50/month with cost anomaly detection — alerts on unexpected RDS/ECS spend
- Manual approval gate before Terraform apply in production

### AWS Resources (provisioned over phases)

| Resource                     | Phase   | Size / Notes                                                                 |
| ---------------------------- | ------- | ---------------------------------------------------------------------------- |
| S3 (receipts, drift reports) | Phase 1 | 3 buckets, SSE-AES256, block public access                                   |
| ECR                          | Phase 1 | Scan on push, keep 25 images                                                 |
| VPC + networking             | Phase 1 | /16 with public/private subnets (LAAD pattern)                               |
| RDS (PostgreSQL 18)          | Phase 1 | db.t3.micro → Multi-AZ in Phase 5, 20GB gp3, encrypted                       |
| Secrets Manager              | Phase 1 | 4 secrets: DB URL, JWT key, Bedrock key, Redis password                      |
| ECS Fargate (API)            | Phase 5 | Auto-scaling (CPU + request count), secrets injection, CloudWatch log driver |
| ALB + ACM + WAF              | Phase 5 | HTTPS, rate-based rules (200/min per IP), SQLi/XSS protection                |
| CloudWatch                   | Phase 5 | Log groups, custom dashboard (p50/p95/p99), metric alarms                    |
| SageMaker serverless         | Phase 5 | Optional LSTM serving path                                                   |
| AWS Budgets + Cost Anomaly   | Phase 5 | $50 monthly budget alert, anomaly detection on RDS + ECS                     |
| EC2 (Airflow)                | Phase 4 | t3.medium, Docker Compose, weekly retraining DAG                             |

---

## CV Narrative

After all six phases, every StockLens CV bullet is replaced with provably true claims:

| Before                                                              | After                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "ARIMA forecasting and Linear Regression for portfolio projections" | "PyTorch LSTM directional classifier (up/flat/down) with 30-day feature window, trained on 50+ S&P 500 components"                                                                                                                                  |
| "Per-category OCR with 78 tests"                                    | "Full-stack Python OCR pipeline with pytesseract + Bedrock Claude Haiku fallback, 80+ pytest suite"                                                                                                                                                 |
| "78 tests covering ML flows"                                        | "LSTM evaluated by directional accuracy, per-class F1, and simulated Sharpe ratio"                                                                                                                                                                  |
| _(no infra claim)_                                                  | "Terraform-provisioned AWS stack: RDS (Multi-AZ, PITR), ECS Fargate (auto-scaling), WAF (rate-based + SQLi/XSS), Secrets Manager (4+ secrets), CloudWatch observability (p50/p95/p99 dashboards), AWS Budgets + cost anomaly detection, OIDC CI/CD" |
| _(no agent claim)_                                                  | "LangChain ReAct agent with 5 financial tools, 15-question golden evaluation set"                                                                                                                                                                   |
| _(no MLOps claim)_                                                  | "Airflow weekly retraining pipeline with Evidently drift detection, champion/challenger model promotion"                                                                                                                                            |
