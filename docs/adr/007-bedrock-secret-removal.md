# ADR 007: Removal of Phantom `BEDROCK_API_KEY` Secret

**Date:** 2026-07-08
**Status:** Accepted
**Phase:** 5 — Production Deployment

## Context

The Phase 5 brief and `docs/TRACKER.md` (line 353) and `docs/MASTER_PLAN.md` (line 394) state that four secrets are injected into the ECS task definition: `DATABASE_URL`, `JWT_SECRET_KEY`, `BEDROCK_API_KEY`, `REDIS_PASSWORD`. The code tells a different story:

- `terraform/secrets.tf` provisions `db_password`, `jwt_secret`, `database_url`, `bedrock_model_id`, `redis_pass`. There is **no `bedrock_api_key` secret**.
- The application calls Bedrock via **IAM-role boto3** (`backend/src/prediction/merchant_map.py:132-134` builds a `bedrock-runtime` client and calls `InvokeModel`). It uses the `BEDROCK_MODEL_ID` env var (a model identifier, e.g. `anthropic.claude-3-haiku-...`), **not** an API key.
- The ECS task role already grants `bedrock:InvokeModel` on the specific model ARN (`terraform/iam.tf`).

`BEDROCK_API_KEY` is a documentation/reality mismatch — a secret that does not exist and is not consumed.

## Decision

Remove `BEDROCK_API_KEY` from the Phase 5 plan, `docs/TRACKER.md`, and `docs/MASTER_PLAN.md`. The correct Bedrock wiring is: IAM task-role permission (`bedrock:InvokeModel`) + the `BEDROCK_MODEL_ID` plain env var already injected at `terraform/ecs.tf:96-98`. No API key is required or created.

## Rationale

- Carrying a phantom secret through the plan would lead an implementer to create a Secrets Manager entry, inject it, and reference a config field that does not exist — wasted work and a broken deploy.
- IAM-role auth is the AWS-recommended, keyless pattern for Bedrock; it is already implemented and already least-priv scoped.

## Consequences

- `docs/MASTER_PLAN.md` line 394 and `docs/TRACKER.md` line 353 must be corrected to list the real four runtime concerns: `DATABASE_URL`, `JWT_SECRET_KEY`, `REDIS_PASSWORD` (auth), `BEDROCK_MODEL_ID` (plain env, not a secret).
- The ECS secret-injection list in `terraform/ecs.tf` stays at `DATABASE_URL` + `JWT_SECRET_KEY`, and **adds `REDIS_PASSWORD`** (see plan Round 1). `bedrock_model_id` remains a plain `environment` var.

## Alternatives Considered

| Alternative                        | Reason Rejected                                                               |
| ---------------------------------- | ----------------------------------------------------------------------------- |
| Keep `BEDROCK_API_KEY` and wire it | No code consumes it; would require adding API-key auth the app doesn't use    |
| Switch Bedrock to API-key auth     | Regresses from the already-working IAM-role pattern; increases secret surface |
