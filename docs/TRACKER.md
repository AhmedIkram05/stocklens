# StockLens — Implementation Tracker

> **Purpose:** Single source of truth for implementation progress. Agents read this to determine what to work on next, and write to it when done.
> **Plan docs:** [MASTER_PLAN.md](MASTER_PLAN.md) (architecture), [PHASE1_IMPLEMENTATION.md](PHASE1_IMPLEMENTATION.md) (Phase 1 blueprint)
> **Docs are frozen** — plan docs are the spec. This tracker captures what actually happened.

---

## Phase 1 — Backend Foundation + Auth + OCR Migration

**Goal:** Eliminate Firebase and Node.js. FastAPI + PostgreSQL is the single backend.
**Cutover:** Big-bang (zero users, no risk).
**Target tests:** 78–95 pytest (async) + existing 78 Jest (preserved).

### Step Tracker

| #   | Step                                                            | Agent                    | Status      | Key Files Built                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Validation                                              | Notes                                                                   |
| --- | --------------------------------------------------------------- | ------------------------ | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------- |
| 1   | Project Scaffold & Docker Compose                               | code-architect / general | ✅ Complete | `backend/Dockerfile`, `backend/pyproject.toml`, `backend/.env.example`, `backend/src/config.py`, `backend/src/main.py`, `docker-compose.yml`, `Makefile`, `backend/src/__init__.py`, `backend/data/.gitkeep`, `backend/alembic/versions/.gitkeep`, `backend/src/database/__init__.py`, `backend/src/auth/__init__.py`, `backend/src/portfolios/__init__.py`, `backend/src/holdings/__init__.py`, `backend/src/transactions/__init__.py`, `backend/src/receipts/__init__.py`, `backend/src/categories/__init__.py`, `backend/src/cache/__init__.py` | LSP import errors expected (packages resolve in Docker) | .gitignore updated: `.env.example` now tracked, `backend/data/` ignored |
| 2   | Database Schema & Migrations (Alembic)                          | code-architect / general | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 3   | Auth Module (JWT + Redis + Rate Limiting)                       | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 4   | Portfolio CRUD                                                  | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 5   | Holdings CRUD                                                   | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 6   | Transactions CRUD                                               | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 7   | Spending Categories & Merchant Mapping                          | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 8   | OCR Pipeline (OpenCV + pytesseract)                             | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 9   | Receipt CRUD + OCR Integration                                  | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 10  | React Native Migration                                          | general (TS)             | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 11  | Terraform Provisioning (VPC + RDS + S3 + ECR + Secrets Manager) | general                  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |
| 12  | Test Suite                                                      | general / code-reviewer  | ⬜ Pending  | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —                                                       | —                                                                       |

### Deviations from Plan

| Step | Planned                                                     | Actual                                  | Rationale                                                                                                            |
| ---- | ----------------------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 1    | `.gitignore` had `.env.example` explicitly listed           | Removed, added `!.env.example` negation | `.env.example` is a template with no secrets — must be tracked                                                       |
| 1    | `docker-compose.yml` shown under `backend/` in plan diagram | Placed at repo root                     | Required for `docker compose up -d` to work from repo root (Makefile target)                                         |
| 1    | Backend data directory name                                 | `backend/data/` with `.gitkeep`         | Added `backend/data/` to `.gitignore` as specified in plan                                                           |
| —    | AWS region defaulted to `us-east-1`                         | Changed to `eu-west-2` (London)         | User requirement. Updated in `config.py` and `.env.example`. Future steps (Terraform, Bedrock) must use `eu-west-2`. |

### Verification Checklist (Phase 1 DoD)

- [ ] `docker compose up -d` succeeds with all services healthy
- [ ] User can register, login, refresh, logout via API
- [ ] Authenticated user can CRUD portfolios, holdings, transactions
- [ ] Receipt upload → OCR extracts total, merchant, line items → category assigned
- [ ] React Native app builds and runs against FastAPI (no Firebase)
- [ ] All 78–95 pytest tests pass
- [ ] All existing 78 Jest tests pass (mocks updated)
- [ ] `ruff check .` — zero errors
- [ ] ESLint — zero errors
- [ ] `npx tsc --noEmit` — zero errors
- [ ] `terraform plan -var="environment=dev"` exits 0
- [ ] IaC security scan passes: `checkov --config-file checkov.yml -d terraform/` and `tfsec terraform/` — zero critical/high
- [ ] Secrets Manager: 4 secrets created and accessible by intended IAM roles
- [ ] Python test coverage ≥80%

### Security Checklist

- [ ] Passwords: bcrypt work factor ≥12
- [ ] JWT: HS256 with ≥256-bit secret
- [ ] Refresh tokens: SHA256 hash in DB, per-session, rotation active
- [ ] Stolen token detection: revoked refresh reuse → all sessions invalidated
- [ ] Logout: revokes specific refresh token + blacklists access token
- [ ] Receipt images: processed in memory, discarded immediately
- [ ] All DB queries: parameterised (`$1`, `$2` via asyncpg)
- [ ] Rate limiting: slowapi + Redis sliding window (20/min auth, 100/min other)
- [ ] CORS: restricted to `http://localhost:8081` (Expo dev)
- [ ] RDS: `storage_encrypted = true`, security group restricted to VPC CIDR
- [ ] Secrets: all production secrets stored in AWS Secrets Manager, never in `.env` files or code
- [ ] IaC security: checkov + tfsec run in CI, critical/high findings block PRs

---

## Future Phases (placeholder sections)

### Phase 2 — Market Data & Portfolio Analytics

_Not started._ Add tracker rows when Phase 2 begins.

### Phase 3 — LSTM & ML Pipeline

_Not started._ Add tracker rows when Phase 3 begins.

### Phase 4 — MLOps & Automation

_Not started._ Add tracker rows when Phase 4 begins.

### Phase 5 — Production AWS Deployment

_Not started._ Add tracker rows when Phase 5 begins.

### Phase 6 — Conversational Agent

_Not started._ Add tracker rows when Phase 6 begins.
