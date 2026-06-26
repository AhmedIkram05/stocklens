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

| #   | Step                                                            | Agent                    | Status     | Key Files Built | Validation | Notes |
| --- | --------------------------------------------------------------- | ------------------------ | ---------- | --------------- | ---------- | ----- |
| 1   | Project Scaffold & Docker Compose                               | code-architect / general | ⬜ Pending | —               | —          | —     |
| 2   | Database Schema & Migrations (Alembic)                          | code-architect / general | ⬜ Pending | —               | —          | —     |
| 3   | Auth Module (JWT + Redis + Rate Limiting)                       | general                  | ⬜ Pending | —               | —          | —     |
| 4   | Portfolio CRUD                                                  | general                  | ⬜ Pending | —               | —          | —     |
| 5   | Holdings CRUD                                                   | general                  | ⬜ Pending | —               | —          | —     |
| 6   | Transactions CRUD                                               | general                  | ⬜ Pending | —               | —          | —     |
| 7   | Spending Categories & Merchant Mapping                          | general                  | ⬜ Pending | —               | —          | —     |
| 8   | OCR Pipeline (OpenCV + pytesseract)                             | general                  | ⬜ Pending | —               | —          | —     |
| 9   | Receipt CRUD + OCR Integration                                  | general                  | ⬜ Pending | —               | —          | —     |
| 10  | React Native Migration                                          | general (TS)             | ⬜ Pending | —               | —          | —     |
| 11  | Terraform Provisioning (VPC + RDS + S3 + ECR + Secrets Manager) | general                  | ⬜ Pending | —               | —          | —     |
| 12  | Test Suite                                                      | general / code-reviewer  | ⬜ Pending | —               | —          | —     |

### Deviations from Plan

| Step | Planned | Actual | Rationale           |
| ---- | ------- | ------ | ------------------- |
| —    | —       | —      | (No deviations yet) |

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
