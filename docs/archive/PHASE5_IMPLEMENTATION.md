# Phase 5 — Production Deployment: FastAPI Serving on AWS ECS Fargate

> **Status:** Draft (pending planner + code-architect review)
> **Last updated:** 2026-07-08
> **Depends on:** Phase 4 (MLOps: retraining DAG, drift detection, champion model, prediction logging)
> **Target audience:** AI agentic coding agents (each round is a self-contained, chronological unit of work with explicit file paths, edits, verification, and edge cases)
> **Architecture decisions:** Locked in grilling session — see `docs/archive/adr/006` (champion delivery), `007` (bedrock secret removal), `008` (remote Terraform state), `009` (ARM64 build)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture (Target End State)](#architecture-target-end-state)
3. [Modules Touched](#modules-touched)
4. [Implementation Rounds](#implementation-rounds)
   - [Round 1 — Terraform Foundation Hardening](#round-1--terraform-foundation-hardening)
   - [Round 2 — Champion Model Delivery (S3 bootstrap)](#round-2--champion-model-delivery-s3-bootstrap)
   - [Round 3 — ECS Auto Scaling + Observability](#round-3--ecs-auto-scaling--observability)
   - [Round 4 — MLflow + Airflow Productionization (P1–P7)](#round-4--mlflow--airflow-productionization-p1p7)
   - [Round 5 — CI/CD Deploy Pipeline (OIDC)](#round-5--cicd-deploy-pipeline-oidc)
   - [Round 6 — Polish, Tests, SageMaker & Verification](#round-6--polish-tests-sagemaker--verification)
5. [Testing Strategy](#testing-strategy)
6. [Success Criteria](#success-criteria)
7. [Risks & Mitigations](#risks--mitigations)
8. [Verification Checklist](#verification-checklist)
9. [ADRs](#adrs)

---

## Overview

Phase 5 migrates StockLens from local Docker Compose to a production AWS deployment. The Phase 4 serving path (`GET /predict/{ticker}`, lifespan-loaded `GlobalLSTM`, 6h Redis result cache, `prediction_log` drift writes) is **reused as-is** — the only serving change is _where the champion model comes from_ (Round 2). The bulk of Phase 5 is infrastructure: harden Terraform, add WAF/auto-scaling/observability/budgets, productionize MLflow + Airflow, and add a CI/CD deploy pipeline.

### Reality Audit (verified against code, not filenames)

| Deliverable (from MASTER_PLAN)                                     | Status          | Evidence                                                                    |
| ------------------------------------------------------------------ | --------------- | --------------------------------------------------------------------------- |
| `/predict` endpoint (champion, 6h Redis cache)                     | ✅ EXISTS       | `backend/src/prediction/router.py:34`, `service.py:40`, `config.py:48`      |
| Redis 6h result cache                                              | ✅ EXISTS       | `router.py:31,117`; `config.py:48` (`PREDICTION_CACHE_TTL=21600`)           |
| `prediction_log` drift writes                                      | ✅ EXISTS       | `backend/src/prediction/prediction_logger.py`                               |
| Load champion **from MLflow** at runtime                           | ❌ MISSING      | runtime loads local `.pt`; no `import mlflow` in `backend/src/`             |
| Champion artifact **delivery into Fargate**                        | ❌ MISSING      | image only `mkdir /model_artifacts/champion` (empty)                        |
| SageMaker serverless path                                          | ❌ MISSING      | zero references anywhere in repo                                            |
| Terraform VPC/RDS/S3/ECR/Redis/IAM/ECS/ALB/Secrets                 | ✅ MOSTLY       | root `.tf` + modules                                                        |
| ALB **HTTP + WAF**                                                 | ❌ MISSING      | HTTP listener commented `ecs.tf:200-212`; WAF module = TODO, not invoked    |
| ACM + custom domain (HTTPS)                                        | ⛔ OUT OF SCOPE | internal Expo Go client uses ALB DNS name over HTTP; no cert/DNS needed     |
| ECS Auto Scaling (CPU + request count)                             | ❌ MISSING      | only `desired_count=2` var                                                  |
| CloudWatch alarms + dashboard                                      | ❌ MISSING      | `modules/monitoring` skeleton, not invoked                                  |
| AWS Budgets + Cost Anomaly (realistic $120 warn / $300 hard)       | ❌ MISSING      | none                                                                        |
| Secrets injected (DB, JWT, REDIS) no `.env`                        | ⚠️ PARTIAL      | only DB+JWT injected; `REDIS_PASSWORD` not wired; `BEDROCK_API_KEY` phantom |
| CI: ruff→pytest→checkov+tfsec→trivy→gitleaks→docker→ECR→ECS (OIDC) | ❌ MISSING      | only lint/type/test/codeql (no IaC/container/secret scanning)               |
| Remote Terraform state                                             | ❌ DISABLED     | `backend "s3"` commented `main.tf:36-42`                                    |

### Key Deliverables

1. **Remote Terraform state** — S3 + DynamoDB lock before prod apply (ADR 008).
2. **HTTP + WAF** — ALB HTTP listener (port 80) in front of Fargate, with WAF (200/min/IP rate limit + SQLi/XSS managed rules) associated to the ALB. No ACM cert / custom domain — the mobile app (Expo Go, internal) calls the AWS-assigned ALB DNS name directly over HTTP.
3. **Champion delivery** — training/Airflow publishes `.pt` to S3; Fargate startup bootstrap downloads it; `load_model` unchanged (ADR 006).
4. **Redis auth** — inject `REDIS_PASSWORD`, build `REDIS_URL` with auth (was passed plaintext, no token).
5. **`.env` guard** — prod ECS task ships no `.env`; `config.py` env_file default overridden.
6. **RDS Multi-AZ** — flip `multi_az=false→true` in production (always on; user directive — production is the only environment, no dev/staging).
7. **Auto scaling** — `aws_appautoscaling` target tracking CPU% + request count.
8. **Observability** — CloudWatch alarms + dashboard (p50/p90/p99 latency, error rate, RDS conns, ECS CPU/mem) + SNS + drift metric filter.
9. **MLflow + Airflow prod** — Airflow (Fargate) + MLflow on RDS-backed Fargate service, IAM/KMS (Compatibility Tracker P1–P7).
10. **CI/CD deploy** — OIDC: ruff→pytest→checkov+tfsec→**trivy (container scan)**→**gitleaks (secret scan)**→docker `--platform linux/arm64`→ECR→terraform→ECS rolling **with automatic rollback on failed health check** (ADR 009).
11. **SageMaker serving path** — config-gated alternate inference route (thin handler inside R6; Fargate stays default for local testing).
12. **Closed-loop MLOps** — drift CloudWatch alarm auto-triggers the Airflow retraining DAG (vs LAAD, which only logs drift); challenger promoted on >2pp, served via R2 bootstrap.
13. **Safe deploys** — ECS deployment circuit breaker rolls back to the last-good task revision on failed health check (zero-downtime, no manual intervention).
14. **Cost control** — Budgets (realistic $120 warn / $300 hard, reconciled from the unrealistic $50/mo) + Cost Anomaly monitors — implemented in R1 alongside foundation hardening (small HCL).

---

## Architecture (Target End State)

```
                         ┌──────────────┐   rate 200/min/IP + SQLi/XSS
   Internet ──HTTP────► │ ALB (HTTP)  │◄──────── WAF v2 Web ACL
                         └──────┬──────┘
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
            ┌──────────┐ ┌──────────┐ ┌──────────┐
            │ ECS Task │ │ ECS Task │ │ ECS Task │   Fargate (ARM64)
            │ uvicorn  │ │ uvicorn  │ │ uvicorn  │   auto-scaled (CPU+req)
            └────┬─────┘ └────┬─────┘ └────┬─────┘
                 │            │            │
     ┌───────────┼────────────┼────────────┼───────────┐
     ▼           ▼            ▼            ▼           ▼
  ┌──────┐  ┌────────┐  ┌──────────┐  ┌──────┐  ┌────────────┐
  │  RDS │  │ Redis  │  │ Secrets  │  │ CW   │  │ S3 (mlflow- │
  │ PG   │  │(auth)  │  │ Manager  │  │Logs/ │  │ artifacts,  │
  │(Multi│  │        │  │(DB,JWT,  │  │Alarms │  │ drift,      │
  │ -AZ) │  │        │  │ REDIS_PW)│  │/Dash) │  │ champion)   │
  └──────┘  └────────┘  └──────────┘  └──────┘  └────────────┘
     ▲                                            ▲
      │ Airflow (Fargate) + MLflow (Fargate, RDS metadata) │ bootstrap download
      │                                            │ champion .pt

  CI/CD (GitHub Actions, OIDC):
     ruff → pytest → checkov+tfsec → docker --platform linux/arm64 → ECR → terraform (remote state) → ECS rolling deploy
```

---

## Modules Touched

```
terraform/
├── main.tf                      # MODIFY: uncomment backend s3; wire waf + monitoring modules
├── variables.tf                 # MODIFY: add waf_rate_limit, autoscale vars, budget_amount + budget_warn_amount, github_repo
├── outputs.tf                   # MODIFY: add waf_arn, dashboard_url, budget_name, alb_dns_name
├── ecs.tf                       # MODIFY: secrets REDIS_PASSWORD; REDIS_URL w/ auth; HTTP listener; entrypoint bootstrap; Multi-AZ n/a here
├── rds.tf                       # MODIFY: multi_az = true (production)
├── waf.tf (or modules/waf)      # NEW: aws_wafv2_web_acl (rate + SQLi/XSS), associate ALB
├── autoscaling.tf               # NEW: appautoscaling target + policies
├── monitoring.tf                # NEW: alarms + dashboard + SNS topic
├── iam.tf                       # MODIFY: champion S3 GetObject; OIDC provider
└── security_groups.tf           # MODIFY: alb_http ingress

backend/
├── Dockerfile                   # MODIFY: add entrypoint bootstrap (model download) before uvicorn
├── docker/bootstrap.sh          # NEW: S3 champion download → /model_artifacts/champion
├── src/config.py                # MODIFY: REDIS_URL from REDIS_PASSWORD; .env guard; champion S3 uri field
├── src/prediction/service.py    # UNCHANGED (loads /model_artifacts/champion/model.pt)
├── ml/mlflow_manager.py         # MODIFY: save_champion_to_disk also pushes to S3
└── .github/workflows/deploy.yml # NEW: OIDC deploy pipeline
```

---

## Implementation Rounds

### Round 1 — Terraform Foundation Hardening

**Objective:** Make the Terraform root production-safe before any apply: enable remote state, remove the phantom `BEDROCK_API_KEY`, wire Redis auth, guard `.env`, enable Multi-AZ, and lay WAF/observability wiring stubs (ALB serves HTTP — no ACM/custom domain).

**Files:** `terraform/main.tf`, `terraform/variables.tf`, `terraform/ecs.tf`, `terraform/rds.tf`, `terraform/iam.tf`, `backend/src/config.py`

**Steps:**

1. **Remote state (ADR 008).** In `terraform/main.tf`, uncomment the `backend "s3"` block (currently lines 36–42). Parameterise:

   ```hcl
   terraform {
     backend "s3" {
       bucket         = var.tf_state_bucket
       key            = "stocklens/${var.environment}/terraform.tfstate"
       region         = "eu-west-2"
       dynamodb_table = var.tf_state_lock_table
       encrypt        = true
     }
   }
   ```

   Add `tf_state_bucket` and `tf_state_lock_table` vars (with defaults) in `variables.tf`. Create the bucket + DynamoDB table once with `bash terraform/scripts/bootstrap-state.sh` (idempotent CLI: creates both, no manual steps), then `terraform init -reconfigure`.

2. **Drop `BEDROCK_API_KEY` (ADR 007).** Confirm `terraform/secrets.tf` has no `bedrock_api_key` (it doesn't). Ensure the ECS secrets block delivers only `DATABASE_URL` + `JWT_SECRET_KEY` + (new) `REDIS_PASSWORD`. `bedrock_model_id` stays a plain `environment` var (already at `ecs.tf:96-98`).

3. **Redis auth.** Currently `ecs.tf:80-82` passes `REDIS_URL = "redis://<host>:6379/0"` with no token, but `elasticache.tf` requires `auth_token` from `redis_pass`. **Do NOT interpolate the secret value into a plaintext `environment` block** (secret _values_ only go in `secrets`). Instead inject `REDIS_HOST` (plain env, from the `aws_elasticache_replication_group` output) + `REDIS_PASSWORD` (secret) and assemble the URL in code:

   ```hcl
   secrets = [
     { name = "DATABASE_URL",   valueFrom = aws_secretsmanager_secret.database_url.arn },
     { name = "JWT_SECRET_KEY", valueFrom = aws_secretsmanager_secret.jwt_secret.arn },
     { name = "REDIS_PASSWORD", valueFrom = aws_secretsmanager_secret.redis_pass.arn },
   ]
   environment = [
     { name = "REDIS_HOST", value = aws_elasticache_replication_group.this.primary_endpoint_address },
     # REDIS_URL is assembled in code from REDIS_HOST + REDIS_PASSWORD (see config.py)
   ]
   ```

4. **`config.py` Redis + `.env` guard.** In `backend/src/config.py`:
   - Line 12 `REDIS_URL = "redis://redis:6379/0"` → derive from `REDIS_HOST` + `REDIS_PASSWORD`:
     ```python
     REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
     REDIS_PASSWORD: str | None = os.getenv("REDIS_PASSWORD")
     if os.getenv("ENVIRONMENT") == "production" and not REDIS_PASSWORD:
         raise RuntimeError("REDIS_PASSWORD is required in production (ElastiCache enforces auth)")
     REDIS_URL: str = f"rediss://:{REDIS_PASSWORD}@{REDIS_HOST}:6379/0" if REDIS_PASSWORD else f"redis://{REDIS_HOST}:6379/0"
     ```
   - Line 68 `env_file=".env"` → guard so prod never reads a shipped `.env`:
     ```python
     # ponytail: .env only in dev; prod ECS task has no .env file, so skip silently
     model_config = SettingsConfigDict(
         env_file=".env" if os.getenv("ENVIRONMENT") != "production" else None,
         extra="ignore",
     )
     ```
   - Add `ENVIRONMENT` already exists (line 41). Add `CHAMPION_S3_URI: str | None = os.getenv("CHAMPION_S3_URI")` for the bootstrap (Round 2).

5. **RDS Multi-AZ.** In `terraform/rds.tf`, set `multi_az = true` (production is the only environment). User directive: Multi-AZ is always on for HA — never disable it for cost.

6. **HTTP + WAF + champion bucket (fully implemented in R1, not stubbed).** Round 1 must produce real resources, not invocations of empty skeletons:
   - **WAF** — implement the `modules/waf` body now (do not leave a TODO). `modules/waf/main.tf`:
     ```hcl
     resource "aws_wafv2_web_acl" "this" {
       name  = "stocklens-waf"
       scope = "REGIONAL"
       default_action { allow {} }
       rule {
         name     = "rate-limit"
         priority = 1
         action { block {} }
         statement {
           rate_based_statement {
             limit              = var.waf_rate_limit   # 200
             aggregate_key_type = "IP"
           }
         }
         visibility_config { cloudwatch_metrics_enabled = true; metric_name = "rate"; sampled_requests_enabled = true }
       }
       rule {
         name     = "sqlixss"
         priority = 2
         override_action { none {} }
         statement {
           managed_rule_group_statement {
             name        = "AWSManagedRulesSQLiRuleSet"
             vendor_name = "AWS"
           }
         }
         visibility_config { cloudwatch_metrics_enabled = true; metric_name = "sqli"; sampled_requests_enabled = true }
       }
       rule {
         name     = "xss"
         priority = 3
         override_action { none {} }
         statement {
           managed_rule_group_statement {
             name        = "AWSManagedRulesXSSRuleSet"
             vendor_name = "AWS"
           }
         }
         visibility_config { cloudwatch_metrics_enabled = true; metric_name = "xss"; sampled_requests_enabled = true }
       }
       visibility_config { cloudwatch_metrics_enabled = true; metric_name = "waf"; sampled_requests_enabled = true }
     }
     resource "aws_wafv2_web_acl_association" "alb" {
       resource_arn = var.alb_arn
       web_acl_arn  = aws_wafv2_web_acl.this.arn
     }
     ```
     `modules/waf/variables.tf`: `alb_arn` (string), `waf_rate_limit` (number, default 200). `modules/waf/outputs.tf`: `web_acl_arn`.
   - **HTTP listener** — in `ecs.tf` configure an ALB `aws_lb_listener` on port 80 (`protocol = "HTTP"`) with `default_action { type = "forward" }` to the target group. No certificate (the mobile client is internal / Expo Go and uses the AWS-assigned ALB DNS name directly). Output `alb_dns_name` so the app and the CI smoke test know the endpoint.
   - **80 ingress (explicit step)** — in `security_groups.tf`, add to the ALB security group:
     ```hcl
     ingress { from_port = 80; to_port = 80; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"]; description = "HTTP from internet" }
     ```
   - **Champion bucket + var** — the S3 `mlflow-artifacts` bucket (already in `modules/s3`) is the champion source. Add `variable "mlflow_artifacts_bucket" { default = "stocklens-mlflow-artifacts" }` and enable **versioning** on that bucket (last-known-good fallback if a bad champion is published — see Risk: SPOF). `CHAMPION_S3_URI` (Round 2) = `s3://${var.mlflow_artifacts_bucket}/champion`.
   - **Monitoring module body** — create `modules/monitoring` in R1 emitting the **SNS topic** (so `module "monitoring"` resolves and `terraform plan` shows a resource); Round 3 adds the alarms + dashboard as additional resources in the same module.
   - **Orphan secret** — `secrets.tf` currently provisions `bedrock_model_id` as a Secrets Manager secret but it is injected as a plain `environment` var (`ecs.tf:96-98`) and never read as a secret. Remove the `bedrock_model_id` secret resource (keep the plain `BEDROCK_MODEL_ID` env). Re-confirm no `BEDROCK_API_KEY` exists (ADR 007).
   - In `main.tf`, wire `module "waf"` (inputs `alb_arn`, `waf_rate_limit`) and `module "monitoring"` (inputs TBD in R3).

7. **Auto-generate secret values (no hand-typed secrets).** In `terraform/secrets.tf`, derive the secret _values_ from `random_password` and write them via `aws_secretsmanager_secret_version` so nothing is pasted in by hand:

   ```hcl
   resource "random_password" "db"    { length = 32; special = false }
   resource "random_password" "jwt"   { length = 48; special = false }
   resource "random_password" "redis" { length = 32; special = false }

   resource "aws_secretsmanager_secret_version" "database_url" {
     secret_id     = aws_secretsmanager_secret.database_url.id
     secret_string = "postgresql://${var.db_username}:${random_password.db.result}@${aws_db_instance.this.address}:5432/${var.db_name}"  # ponytail: use your actual RDS resource/endpoint output name
   }
   resource "aws_secretsmanager_secret_version" "jwt_secret" {
     secret_id     = aws_secretsmanager_secret.jwt_secret.id
     secret_string = random_password.jwt.result
   }
   resource "aws_secretsmanager_secret_version" "redis_pass" {
     secret_id     = aws_secretsmanager_secret.redis_pass.id
     secret_string = random_password.redis.result
   }
   ```

   The ECS `secrets` block (steps 2–3) reads the ARNs; the _values_ are now produced by Terraform, eliminating manual secret entry.

8. **Budgets + Cost Anomaly (merged from former R4 — small HCL, no need for a separate round).** In `terraform/budgets.tf`:

   ```hcl
   resource "aws_budgets_budget" "monthly" {
     name         = "stocklens-monthly"
     budget_type  = "COST"
     limit_amount = var.budget_monthly_amount   # "300" (hard); 80% notification ~$240 warn
     limit_unit   = "USD"
     time_unit    = "MONTHLY"
     notification {
       comparison_operator = "GREATER_THAN"
       threshold           = 80
       threshold_type      = "PERCENTAGE"
       notification_type   = "ACTUAL"
       subscriber_email_addresses = [var.billing_alert_email]
     }
   }
   resource "aws_budgets_budget" "warn" {
     name         = "stocklens-monthly-warn"
     budget_type  = "COST"
     limit_amount = var.budget_warn_amount   # "120" (early warn)
     limit_unit   = "USD"
     time_unit    = "MONTHLY"
     notification {
       comparison_operator = "GREATER_THAN"
       threshold           = 100
       threshold_type      = "PERCENTAGE"
       notification_type   = "ACTUAL"
       subscriber_email_addresses = [var.billing_alert_email]
     }
   }
   resource "aws_ce_anomaly_monitor" "svc" {
     name           = "stocklens-svc"
     monitor_type   = "DIMENSIONAL"
     monitor_dimension = "SERVICE"
   }
   resource "aws_ce_anomaly_subscription" "email" {
     name      = "stocklens-anomaly"
     threshold = 50
     frequency = "DAILY"
     monitor_arn = aws_ce_anomaly_monitor.svc.arn
     subscribers { type = "EMAIL", address = var.billing_alert_email }
   }
   ```

   Add `budget_monthly_amount`, `budget_warn_amount`, `billing_alert_email` vars to `variables.tf`.

   **Edge Cases:** Anomaly monitors need ~1 day of billing history before they fire; cannot verify same-day. Budget 80% notification is the practical early-warning.

**Verify:**

- `terraform plan` shows WAF + budgets + anomaly monitor: `aws_wafv2_web_acl`, `aws_wafv2_web_acl_association`, `aws_budgets_budget` (x2), `aws_ce_anomaly_monitor` + `aws_ce_anomaly_subscription`.

**Edge Cases:**

- Remote-state bootstrap: the bucket + lock table cannot use the remote backend themselves. `terraform/scripts/bootstrap-state.sh` creates both idempotently via CLI — run it once, fully scripted (no manual clicks).
  - No ACM/DNS: the ALB is reached via its AWS-assigned DNS name (`alb_dns_name` output) over HTTP — acceptable because the mobile client is internal (Expo Go), not a public web app.
- `rediss://` (TLS) is required because ElastiCache forces in-transit encryption — plain `redis://` will reject auth.
- ElastiCache uses AWS-managed self-signed certs; set `ssl_cert_reqs=None` in the redis client config or the connection fails on cert verification.

---

### Round 2 — Champion Model Delivery (S3 bootstrap)

**Objective:** Get the champion `.pt` into the stateless Fargate task at startup (ADR 006). Reuses the existing `save_champion_to_disk` promotion; adds an S3 publish + a container bootstrap download. `prediction_service.load_model` is unchanged.

**Files:** `backend/ml/mlflow_manager.py`, `backend/docker/bootstrap.sh`, `backend/Dockerfile`, `terraform/ecs.tf`, `terraform/iam.tf`

**Steps:**

1. **Publish champion to S3 at promotion.** In `mlflow_manager.py::save_champion_to_disk`, after writing `/model_artifacts/champion/*` locally, also `put_object` each file to `s3://<mlflow-artifacts>/champion/`. Use boto3 (already a dependency). The destination bucket/prefix comes from `MLFLOW_ARTIFACT_BUCKET` (set in training env). Gate on env presence so local dev is unaffected.

2. **Bootstrap downloader.** New `backend/docker/bootstrap.py` (Python + boto3, keeps the image lean — no `awscli` layer; matches ADR 006 rationale):

   ```python
   #!/usr/bin/env python3
   import os, sys, boto3
   from pathlib import Path

   CHAMPION_S3_URI = os.getenv("CHAMPION_S3_URI", "")
   if os.getenv("ENVIRONMENT") == "production" and not CHAMPION_S3_URI:
       print("[bootstrap] FATAL: CHAMPION_S3_URI required in production", file=sys.stderr)
       sys.exit(1)  # prod fast-fail: never serve a model-less task
   if CHAMPION_S3_URI:
       dest = Path("/model_artifacts/champion")
       dest.mkdir(parents=True, exist_ok=True)
       print(f"[bootstrap] downloading champion from {CHAMPION_S3_URI}")
       # bucket/key parsed from s3://bucket/prefix
       _, _, path = CHAMPION_S3_URI.partition("s3://")
       bucket, _, prefix = path.partition("/")
       s3 = boto3.client("s3")
       paginator = s3.get_paginator("list_objects_v2")
       found = False
       for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
           for obj in page.get("Contents", []):
               rel = obj["Key"][len(prefix):].lstrip("/")
               if not rel:
                   continue
               local = dest / rel
               local.parent.mkdir(parents=True, exist_ok=True)
               s3.download_file(bucket, obj["Key"], str(local))
               found = True
       if not found:
           print("[bootstrap] FATAL: no champion objects at prefix", file=sys.stderr)
           sys.exit(1)
   # hand off to uvicorn (or whatever CMD was passed)
   os.execvp(sys.argv[1], sys.argv[1:])
   ```

   S3 **versioning** on the `mlflow-artifacts` bucket (Round 1) enables manual revert to a prior `champion/` version if a bad champion is published. Add a CloudWatch alarm on bootstrap `exit 1` (non-zero task exit) so a model-delivery outage pages on-call.

3. **Dockerfile entrypoint + ARM64 wheel (ADR 009 / M1).** In `backend/Dockerfile`:

   ```dockerfile
   COPY docker/bootstrap.py /usr/local/bin/bootstrap.py
   ENTRYPOINT ["python", "/usr/local/bin/bootstrap.py"]
   CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
   ```

   The Rust features-engine wheel must be **`aarch64`**, not the default amd64, or it import-crashes inside the ARM64 container (QEMU only emulates the final image, not the compiled `.so`). Pin the maturin build stage: `maturin build --release --target aarch64-unknown-linux-gnu` (or set `ENV CARGO_BUILD_TARGET=aarch64-unknown-linux-gnu`). The `docker buildx build --platform linux/arm64` in Round 5 then produces a consistent ARM64 image. Note: `CARGO_BUILD_TARGET` alone is insufficient — the build stage must install `gcc-aarch64-linux-gnu` and set `CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc` (no linker → the wheel build fails at link time).

4. **ECS task role S3 read.** In `terraform/iam.tf`, add to the ECS task role policy:
   ```hcl
   {
     "Effect": "Allow",
     "Action": ["s3:GetObject", "s3:ListBucket"],
     "Resource": [
       "arn:aws:s3:::${var.mlflow_artifacts_bucket}",
       "arn:aws:s3:::${var.mlflow_artifacts_bucket}/champion/*"
     ]
   }
   ```
5. **Pass `CHAMPION_S3_URI`** as plain `environment` in `ecs.tf` (from the `mlflow-artifacts` bucket output).

**Verify:**

- Build image, run locally with `CHAMPION_S3_URI=s3://<bucket>/champion` + AWS creds → container starts, `/model_artifacts/champion/model.pt` present, `/predict/AAPL` returns.
- Simulate missing bucket → container exits non-zero (fast-fail verified).
- `prediction_service.load_model` source untouched (grep confirm).

**Edge Cases:**

- Bootstrap must run **before** `lifespan.load_model` — ENTRYPOINT chain guarantees ordering.
- `awscli` bloat vs boto3 downloader: prefer a ~15-line Python `boto3` downloader (`docker/bootstrap.py`) to avoid a 50MB awscli layer in the lean image (keep image small — aligns with ADR 006 rationale).
- Champion changes weekly: new task revision re-runs bootstrap; old tasks keep serving old model until replaced (acceptable; Redis result cache keyed by ticker, not version).

---

### Round 3 — ECS Auto Scaling + Observability

**Objective:** Target-tracking auto scaling (CPU + request count) and CloudWatch alarms + dashboard (p50/p90/p99 latency, error rate, RDS conns, ECS CPU/mem) with SNS alerting and a drift metric filter.

**Files:** `terraform/autoscaling.tf`, `terraform/monitoring.tf`, `terraform/ecs.tf`, `terraform/variables.tf`

**Steps:**

1. **Auto scaling.** New `autoscaling.tf`:

   ```hcl
   resource "aws_appautoscaling_target" "ecs" {
     max_capacity       = var.ecs_max_capacity
     min_capacity       = var.ecs_min_capacity
     resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this.name}"
     scalable_dimension = "ecs:service:DesiredCount"
     service_namespace  = "ecs"
   }
   resource "aws_appautoscaling_policy" "cpu" {
     name               = "cpu-target"
     policy_type        = "TargetTrackingScaling"
     resource_id        = aws_appautoscaling_target.ecs.resource_id
     scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
     service_namespace  = aws_appautoscaling_target.ecs.service_namespace
      target_tracking_scaling_policy_configuration {
        predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
        target_value = var.ecs_cpu_target
      }
    }
    resource "aws_appautoscaling_policy" "ecs_rps" {
      name               = "stocklens-ecs-rps"
      service_namespace  = aws_appautoscaling_target.ecs.service_namespace
      resource_id        = aws_appautoscaling_target.ecs.resource_id
      scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
      target_tracking_scaling_policy_configuration {
        predefined_metric_specification { predefined_metric_type = "ECSServiceAverageRequestCount" }
        target_value = var.ecs_rps_target
      }
    }
   ```

2. **Monitoring.** New `monitoring.tf`:
   - `aws_sns_topic` `stocklens-alerts` + `aws_sns_topic_subscription` (email from `var.billing_alert_email`). **Required human step:** the subscriber must click the SNS confirmation email before alerts deliver — note this as a manual gate, not an automated step.
   - Alarms: ECS CPU > 80%, ECS memory > 80%, ALB 5xx > threshold, ALB target 4xx rate, RDS free storage < 10%, RDS connections > 80% `max_connections`.
   - Latency p50/p99: `aws_cloudwatch_metric_alarm` on `AWS/ApplicationELB` `TargetResponseTime` with `extended_statistic` "p99" (CloudWatch natively emits p50/p90/p99 for `TargetResponseTime` — no access-log dependency needed; if a literal p95 widget is required, build it via CloudWatch metric-math, not the raw statistic).
   - Dashboard `aws_cloudwatch_dashboard` with widgets: latency p50/90/99, HTTP 2xx/4xx/5xx, ECS CPU/mem, RDS connections, Redis CPU.
   - Drift alert metric filter: `aws_cloudwatch_log_metric_filter` on the existing structlog drift alert (`"drift_alert"` / `alert_triggered=true`) → custom metric → alarm → SNS (reuses Phase 4 drift alert log line).

**Verify:**

```bash
terraform plan   # shows appautoscaling + 8 alarms + 1 dashboard + SNS
aws cloudwatch get-dashboard --dashboard-name stocklens-prod
```

- Manually scale test: `aws ecs update-service --desired-count 1` then generate load → desired count climbs toward `max_capacity`.

**Edge Cases:**

- `min_capacity` must be ≥ 2 for HA (AZ spread); `max_capacity` bounded by the realistic cost guardrail (Round 1: $300 hard) — pick 2→6.
- p99 latency is a native `AWS/ApplicationELB` `TargetResponseTime` metric (no access-log dependency); enable ALB access logs separately only if you want detailed request records.
- SNS email subscription requires confirmation click — automate via var or note manual confirm.

---

### Round 4 — MLflow + Airflow Productionization (Compatibility Tracker P1–P7)

**Objective:** Move MLflow + Airflow off SQLite/local-state to production-grade (RDS PostgreSQL metadata, S3 artifact store, IAM/KMS). Airflow runs as **self-managed ECS Fargate** services (scheduler + webserver) — the same Fargate pattern as the API — with MLflow as a **Fargate service** with an RDS-backed store. Addresses TRACKER Compatibility P1–P6. (Chosen over MWAA: MWAA's ~$400/mo minimum exceeds the $300 hard budget for a once-weekly job; Fargate Airflow is ~$30–50/mo and reuses the existing ECS pattern.)

**Files:** `backend/ml/config.py`, `terraform/` (new `mlflow.tf` Fargate service + `airflow.tf` Fargate services + IAM/KMS), `terraform/iam.tf`

**Steps:**

- **P1 (Airflow → Backend network):** Airflow Fargate services deploy into the StockLens VPC private subnets so they reach the RDS instance and S3. The retraining DAG uses `DATABASE_URL` (prod RDS) instead of local postgres. Same VPC/private subnets + SG allow.
- **P2 (Shared model volumes → S3/EFS):** Champion + artifacts use S3 (`mlflow-artifacts`) — Round 2 already publishes there. MLflow artifact root = `s3://<bucket>/`. Remove local volume mounts.
- **P3 (MLflow SQLite → RDS) + Fargate service:** New `terraform/mlflow.tf`:
  - A dedicated `mlflow` database/schema on the existing RDS instance (or a small `db.t4g.micro`).
  - An `aws_ecs_task_definition` + `aws_ecs_service` running the MLflow tracking server container (`ghcr.io/mlflow/mlflow` or public ECR) with `MLFLOW_BACKEND_STORE_URI=postgresql://...` and `MLFLOW_DEFAULT_ARTIFACT_ROOT=s3://<bucket>/`. SG allows 5000/tcp from the Airflow SG + backend SG.
  - One-off `mlflow db upgrade` via a short-lived Fargate task (or as the service container's startup command) so the `champion` registry alias is durable (retires SQLite).
- **P4 (Airflow Fargate services + ML container → EcsRunTaskOperator):** New `terraform/airflow.tf` runs the Airflow **webserver** and **scheduler** as two Fargate services (single-task, `LocalExecutor` — fine for weekly cadence) with `AIRFLOW__CORE__SQL_ALCHEMY_CONN = postgresql://...` (RDS) and `airflow db migrate` on first boot. The weekly retraining container (`ml.pipeline`) is invoked from Airflow via `EcsRunTaskOperator` targeting the retraining task definition. The Airflow task role gets `ecs:RunTask` + `iam:PassRole` for the retraining task role. (The Phase 4 local `docker compose run ml` path remains for dev.)
- **P5 (S3 IAM/KMS):** Scoped roles for (a) the **Airflow task role**, (b) the **MLflow Fargate task role**, (c) the **retraining ECS task role**, (d) the **backend task role** (already has `champion/*` read). Concretely in `terraform/iam.tf`:
  ```hcl
  resource "aws_iam_role" "airflow" {  # Airflow Fargate task role
    assume_role_policy = jsonencode({
      Version = "2012-10-17"
      Statement = [{ Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" }, Effect = "Allow" }]
    })
  }
  resource "aws_iam_role_policy" "airflow_s3_kms" {
    role = aws_iam_role.airflow.id
    policy = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetObjectVersion"],
          Resource = [aws_s3_bucket.mlflow_artifacts.arn, "${aws_s3_bucket.mlflow_artifacts.arn}/*",
                      aws_s3_bucket.drift_reports.arn, "${aws_s3_bucket.drift_reports.arn}/*"] },
        { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = [aws_kms_key.s3.arn] },
        { Effect = "Allow", Action = ["ecs:RunTask", "iam:PassRole"], Resource = "*" }   # retraining EcsRunTaskOperator
      ]
    })
  }
  ```
  The SSE-KMS key (`aws_kms_key.s3`) is created in `modules/s3`; bucket policy enforces `aws:SecureTransport` + `s3:x-amz-server-side-encryption:aws:kms`.
  > **Dependency ordering:** the IAM policy above references `aws_kms_key.s3.arn` — ensure the KMS key resource exists in `modules/s3` before this policy is applied. Terraform resolves this via implicit reference; if the key is in a separate module, add an explicit `depends_on` or ensure the module is wired in `main.tf` before the IAM module.
- **P6 (CloudWatch alerting):** Airflow + MLflow Fargate log to CloudWatch via `awslogs`. The drift alert metric filter from Round 3 covers model drift.
- **P7 (Closed-loop drift → auto-retrain):** Wire the Round 3 drift CloudWatch alarm to re-trigger the `weekly_retraining` DAG automatically:
  ```hcl
  resource "aws_cloudwatch_event_rule" "drift_retrain" {
    name        = "stocklens-drift-retrain"
    event_pattern = jsonencode({ source = ["aws.cloudwatch"], detail-type = ["CloudWatch Alarm State Change"],
      detail = { alarm-name = [aws_cloudwatch_metric_alarm.drift.name], state = { value = ["ALARM"] } } })
  }
  resource "aws_cloudwatch_event_target" "drift_retrain_task" {
    rule      = aws_cloudwatch_event_rule.drift_retrain.name
    target_id = "TriggerRetrain"
    arn       = aws_ecs_cluster.this.arn
    ecs_target {
      task_definition_arn = aws_ecs_task_definition.trigger_retrain.arn
      launch_type         = "FARGATE"
      network_configuration { assign_public_ip = false; subnets = var.private_subnets; security_groups = [aws_security_group.airflow.id] }
    }
  }
  ```
  The `trigger_retrain` task runs `airflow dags trigger weekly_retraining` (IAM-native via `ecs:RunTask`, no REST token/SSM). This closes the MLOps loop: drift detected → EventBridge → ECS RunTask → Airflow runs retraining DAG → challenger evaluated vs champion → promote if >2pp → next Fargate deploy serves new champion (R2 bootstrap). This is the differentiator vs LAAD, which only logs SageMaker drift without auto-retraining.

**Verify:** `aws ecs run-task --cluster stocklens --task-definition trigger_retrain --command "airflow dags list"` shows `weekly_retraining`; one manual DAG run promotes champion → S3 → next Fargate deploy serves new model. Simulate the drift alarm (set to ALARM) → EventBridge → ECS RunTask → Airflow DAG run auto-starts.

**Edge Cases:**

- RDS PostgreSQL for Airflow + MLflow backends requires `airflow db migrate` / `mlflow db upgrade` before first serve (run once via a Fargate task or startup command).
- LocalExecutor single scheduler is fine for weekly cadence; `EcsRunTaskOperator` isolates the heavy training container so the always-on scheduler stays tiny (~0.5 vCPU).
- The retraining `EcsRunTaskOperator` needs the retraining task definition + IAM pass-role wired (P4/P5) or the trigger fails at runtime.
- Airflow Fargate scheduler is always-on (~0.5 vCPU ≈ $15/mo) — far cheaper than MWAA's ~$400/mo, and stays within the $300 budget.

---

### Round 5 — CI/CD Deploy Pipeline (OIDC)

**Objective:** GitHub Actions OIDC deploy: ruff → pytest → checkov+tfsec → docker `--platform linux/arm64` → ECR → terraform (remote state) → ECS rolling. No long-lived AWS keys.

**Files:** `.github/workflows/deploy.yml`, `terraform/iam.tf` (OIDC provider)

**Steps:**

1. **OIDC provider.** In `iam.tf` add `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com`, plus a deploy role whose trust policy pins the **repo + branch** so no other repo/branch can assume it:

   ```hcl
   resource "aws_iam_openid_connect_provider" "github" {
     url             = "https://token.actions.githubusercontent.com"
     client_id_list  = ["sts.amazonaws.com"]
     thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]  # GitHub OIDC thumbprint — ponytail: GitHub rotates these occasionally; check https://github.blog/changelog/ for updates
   }
   data "aws_iam_policy_document" "github_oidc_assume" {
     statement {
       actions = ["sts:AssumeRoleWithWebIdentity"]
       principals { type = "Federated", identifiers = [aws_iam_openid_connect_provider.github.arn] }
       condition {
         test     = "StringEquals"
         variable = "token.actions.githubusercontent.com:aud"
         values   = ["sts.amazonaws.com"]
       }
        condition {
          test     = "StringLike"
          variable = "token.actions.githubusercontent.com:sub"
          values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
        }
     }
   }
   resource "aws_iam_role" "deploy" {
     name               = "stocklens-github-deploy"
      assume_role_policy = data.aws_iam_policy_document.github_oidc_assume.json
      # deploy role needs broad apply perms (whole stack: IAM, WAF, RDS, S3, Budgets,
      # AutoScaling, CloudWatch, SNS, KMS, ECR, ECS, ELB, ElastiCache, CE, Lambda)
      inline_policy {
        name = "stocklens-deploy"
        policy = jsonencode({
          Version = "2012-10-17"
          Statement = [
            {
              Effect = "Allow"
              Action = [
                "ecr:*", "ecs:*", "s3:*", "dynamodb:*", "kms:*",
                "iam:PassRole", "iam:GetRole", "iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy",
                "cloudwatch:*", "events:*", "sns:*", "budgets:*", "ce:*", "wafv2:*",
                "elasticache:*", "rds:*", "application-autoscaling:*", "logs:*",
                "elasticloadbalancing:*", "lambda:*"
              ]
              Resource = "*"
            }
          ]
        })
      }
    }
   ```

   Replace `owner/stocklens` with the real GitHub org/repo. Reference `aws_iam_role.deploy.arn` in `outputs.tf` as `ecs_deploy_role_arn` (consumed by `deploy.yml` via `secrets.ECS_DEPLOY_ROLE_ARN`).

Add `variable "github_repo" { default = "owner/stocklens" }` to `variables.tf` and set it to the real `org/repo` so the trust condition above matches. Then set the GitHub repo secret once (scriptable — no UI click):

```bash
gh secret set ECS_DEPLOY_ROLE_ARN \
  --repo "<real-org>/stocklens" \
  --body "$(terraform -chdir=terraform output -raw ecs_deploy_role_arn)"
```

2. **Deploy workflow** `.github/workflows/deploy.yml`:
   ```yaml
   on:
   push:
   branches: [main]
   jobs:
   test:
   runs-on: ubuntu-latest
   steps: - uses: actions/checkout@v4 - run: ruff check backend/ && ruff format --check backend/ - run: cd backend && pytest -q
   iac-scan:
   runs-on: ubuntu-latest
   steps: - uses: actions/checkout@v4 - uses: bridgecrewio/checkov-action@master
   with: { directory: terraform/ } - run: tfsec terraform/ # install via aquasecurity/tfsec-action
   container-scan:
   runs-on: ubuntu-latest
   needs: [build-push]
   steps: - uses: aquasecurity/trivy-action@master
   with: { image-ref: "$ECR_URL:${{ github.sha }}", severity: "CRITICAL,HIGH", exit-code: "1" }
   secret-scan:
   runs-on: ubuntu-latest
   steps: - uses: actions/checkout@v4 - uses: gitleaks/gitleaks-action@v2
   build-push:
   runs-on: ubuntu-latest
   steps: - uses: aws-actions/configure-aws-credentials@v4
   with: { role-to-assume: ${{ secrets.ECS_DEPLOY_ROLE_ARN }}, aws-region: eu-west-2 }

   ```

- uses: docker/setup-buildx-action@v3 - uses: docker/setup-qemu-action@v3 # ADR 009: QEMU for arm64 emulation on x86 runners - run: cd backend && docker buildx build --platform linux/arm64 -f backend/Dockerfile -t $ECR_URL:${{ github.sha }} --push . # explicit backend/ context + Dockerfile path (ADR 009)
  deploy:
  needs: [test, iac-scan, container-scan, secret-scan, build-push]
  environment: production # requires manual approval
  steps: - uses: aws-actions/configure-aws-credentials@v4
  with: { role-to-assume: ${{ secrets.ECS_DEPLOY_ROLE_ARN }}, aws-region: eu-west-2 } - run: cd terraform && terraform init && terraform apply -auto-approve
  ````

  3. **Automatic rollback on failed deploy.** In `terraform/ecs.tf`, enable the ECS deployment circuit breaker so a task that fails its health check rolls back to the previous stable revision instead of leaving the service unhealthy:

    ```hcl
    resource "aws_ecs_service" "api" {
      # ... existing config ...
      deployment_controller { type = "ECS" }
      deployment_circuit_breaker {
        enable   = true
        rollback = true   # automatic rollback to last-good task def on failed health check
      }
    }
    ```

    Combined with the manual `production` approval gate (Step 2), this yields safe zero-downtime deploys: a bad image is auto-rolled-back and never served to users.
  ````

**Verify:** Push to `Phase-5/Planning` → `deploy.yml` runs; ECR gets an `arm64` image; `terraform apply` uses remote state; ECS force-new-deployment pulls new task (bootstrap downloads champion). Manual approval gate on `production` env.

**Edge Cases:**

- `docker buildx --platform linux/arm64` on x86 runners needs QEMU (`docker/setup-qemu-action`) OR a native ARM runner. The `maturin` Rust wheel must be `aarch64` (ADR 009).
- OIDC subject condition must pin the repo + branch to avoid cross-repo assumption.
- `terraform apply` in CI must use the same remote state bucket as humans (Round 1) — single source of truth.

---

### Round 6 — Polish, Tests, SageMaker & Verification

**Objective:** End-to-end verification, drift S3 bucket Terraform-managed (currently deferred), ruff clean, docs updated. Config-gated SageMaker alternate inference route (`PREDICTION_SERVING_BACKEND = fargate | sagemaker`).

**Steps:**

- Ensure `stocklens-drift-reports` S3 bucket is created via Terraform (currently referenced in config but bucket creation deferred to Phase 5 — add to `modules/s3` or `rds.tf`/s3 module).
- Run full `ruff check backend/`, `pytest backend/`, `checkov -d terraform/`, `tfsec terraform/`.
- **SageMaker serving path.** Add `PREDICTION_SERVING_BACKEND: str = os.getenv("PREDICTION_SERVING_BACKEND", "fargate")` to `config.py`. In `service.py`, if `sagemaker`, invoke `boto3` `sagemaker-runtime` `InvokeEndpoint` instead of local `GlobalLSTM` (default path unchanged). Create `terraform/sagemaker.tf`: package a thin Python handler that `import`s `backend.src.prediction.service` directly (no standalone `inference.py` — reuse the existing feature pipeline + load_model). Deploy via `aws_sagemaker_model` + `ServerlessConfig` (256 KB payload cap, bounded concurrency). The `PREDICTION_SERVING_BACKEND=sagemaker` request/response contract is identical to Fargate. SageMaker serverless cold start adds latency; account for it in latency budgets. Both paths must be verified working end-to-end.
- Deploy to production, smoke test `/health`, `/predict/AAPL`, drift endpoint, dashboard renders.
- Update `docs/CONTEXT.md` (Production Deployment glossary) and `docs/TRACKER.md` Phase 5 (Step Tracker + Deviations + Verification).
- Mark `BEDROCK_API_KEY` removed in MASTER_PLAN/TRACKER (ADR 007).

**Verify:** [Verification Checklist](#verification-checklist) all green.

---

## Testing Strategy

| Layer         | Test                                                                                                             | Command                                                        |
| ------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Config        | `REDIS_URL` builds with auth; `.env` skipped in production                                                       | `pytest backend/tests/test_config.py`                          |
| Bootstrap     | champion download succeeds / fails-fast on missing bucket                                                        | unit test `docker/bootstrap.py` (mocked boto3)                 |
| Serving       | `/predict/{ticker}` returns correct shape with S3-delivered model                                                | `pytest backend/tests/test_prediction.py`                      |
| IaC           | `terraform validate` + `checkov` + `tfsec` clean                                                                 | CI `iac-scan` job                                              |
| Deploy (prod) | ALB HTTP 200 (`curl http://$(terraform output alb_dns_name)`), WAF blocks >200 req/min/IP, p90 latency dashboard | manual smoke + `curl` loop                                     |
| Drift alert   | structlog drift alert → CloudWatch metric → SNS                                                                  | inject test drift log line                                     |
| SageMaker     | `PREDICTION_SERVING_BACKEND=sagemaker` → `/predict` returns same shape as Fargate                                | `pytest backend/tests/test_prediction.py` or manual smoke test |

---

## Success Criteria

1. `GET /predict/{ticker}` serves from a champion model delivered via S3 bootstrap on a stateless Fargate task (no baked-in `.pt`, no MLflow runtime dep).
2. The ALB serves the API over HTTP (AWS-assigned DNS name, internal Expo Go client) with WAF enforcing 200 req/min/IP + SQLi/XSS in front of Fargate. No ACM cert / custom domain.
3. Redis is authenticated (`rediss://` + `REDIS_PASSWORD`); no `.env` in prod.
4. ECS auto-scales on CPU + request count; CloudWatch dashboard shows p50/p90/p99 + error rate + RDS/ECS health; SNS alerts fire.
5. Monthly budget with 80% warn alert (realistic $120 warn / $300 hard) + Cost Anomaly monitor active.
6. MLflow + Airflow run on RDS PostgreSQL (no SQLite), S3 artifacts, IAM/KMS scoped.
7. CI/CD deploys via OIDC with ruff→pytest→checkov+tfsec→trivy→gitleaks→arm64 docker→ECR→terraform→ECS; automatic rollback on failed health check; manual approval on prod.
8. Terraform state is remote (S3 + DynamoDB lock).
9. SageMaker alternate serving path works: `PREDICTION_SERVING_BACKEND=sagemaker` routes `/predict` to SageMaker endpoint with identical response contract.

---

## Risks & Mitigations

| Risk                                                                                                                                                                                                                                                                                                                     | Mitigation                                                                                                                                                                                                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| amd64 image on ARM64 task (exec format error)                                                                                                                                                                                                                                                                            | buildx `--platform linux/arm64` (ADR 009); smoke test catches at first deploy                                                                                                                                                                                                                             |
| Champion download fails at startup → model-less task                                                                                                                                                                                                                                                                     | bootstrap `exit 1` fast-fail; ECS keeps last good task                                                                                                                                                                                                                                                    |
| WAF too strict blocks legit traffic                                                                                                                                                                                                                                                                                      | block from day 1 at 200/min/IP (user directive); adjust rate limit up if collateral damage observed                                                                                                                                                                                                       |
| Remote state lock contention in CI                                                                                                                                                                                                                                                                                       | DynamoDB lock (ADR 008); serialise prod deploy job                                                                                                                                                                                                                                                        |
| RDS Multi-AZ cost (always on) exceeds the $300 hard budget                                                                                                                                                                                                                                                               | budget alert + right-size `db.t4g.micro`; Multi-AZ forced ON in production (user directive — prod-only)                                                                                                                                                                                                   |
| Phantom `BEDROCK_API_KEY` re-added                                                                                                                                                                                                                                                                                       | ADR 007 removes it from docs; CI grep guard                                                                                                                                                                                                                                                               |
| Airflow→RDS migration breaks retraining                                                                                                                                                                                                                                                                                  | take an RDS snapshot before `airflow db migrate`; validate on a restored snapshot; `airflow db migrate` not `init` (no staging env exists — prod is the only one)                                                                                                                                         |
| **Budget $50/mo unrealistic** — Two scopes: **serving stack only** (Multi-AZ RDS + ElastiCache + 2× Fargate 2 vCPU + ALB + NAT + WAF) ≈ **$90–130/mo** at rest; **full prod incl. Airflow (t3.medium) + MLflow (t3.small)** ≈ **$300–400/mo** (per Phase 4 TRACKER note 357). Auto-scaling to 6 tasks blows past either. | Reconciled: budget threshold set to realistic $120 warn / $300 hard (Round 1), replacing the $50/mo claim. Multi-AZ forced ON in production (user directive — prod-only). The Cost Anomaly monitor (50% spend-deviation alert) provides early warning, distinct from the $120/$300 budget caps (Round 1). |
| **Champion S3 is a SPOF** — deleted/unreachable `champion/` object → all new tasks fast-fail → total capacity loss                                                                                                                                                                                                       | S3 versioning on `mlflow-artifacts`; bootstrap falls back to **last-known-good** `model.pt` (previous version) when the latest fetch fails; CloudWatch alarm on bootstrap `exit 1` pages on-call.                                                                                                         |

---

## Verification Checklist

- [ ] `terraform init -reconfigure` uses S3 + DynamoDB (no local `terraform.tfstate` committed)
- [ ] `grep -r BEDROCK_API_KEY terraform/ backend/` → no matches
- [ ] `REDIS_URL` in prod task contains `rediss://:***@` (auth present); `ssl_cert_reqs=None` configured for ElastiCache AWS-managed certs
- [ ] `ENVIRONMENT=production` → `config.py` does NOT load `.env`
- [ ] ALB `alb_dns_name` reachable on `:80` (HTTP 200/OK); WAF associated, no ACM/custom-domain dependency (blocks from day 1)
- [ ] `aws wafv2` Web ACL associated to ALB; rate rule 200/min/IP blocking (not metrics-only); SQLi + XSS managed rule groups present
- [ ] `aws appautoscaling` target + 2 policies created; min 2 / max 6
- [ ] CloudWatch dashboard renders; 8 alarms + SNS subscription confirmed
- [ ] `aws budgets` + `ce_anomaly_monitor` present (threshold reconciled to $120 warn / $300 hard)
- [ ] MLflow + Airflow metadata on RDS PostgreSQL (no SQLite); retraining DAG promotes → S3
- [ ] `deploy.yml` OIDC role assumed; `docker buildx --platform linux/arm64` pushed to ECR (with QEMU step for x86 runners)
- [ ] `ECS force-new-deployment` → task RUNNING on ARM64 with champion model loaded
- [ ] Closed-loop MLOps: EventBridge rule on drift CloudWatch alarm auto-triggers `weekly_retraining` DAG (promotes challenger on >2pp)
- [ ] ECS `deployment_circuit_breaker` `rollback = true`; failed deploy auto-rolls back to prior task revision
- [ ] CI `trivy` (no CRITICAL/HIGH) + `gitleaks` pass; `checkov`+`tfsec` green
- [ ] `/predict/AAPL` returns `{ticker, prediction, confidence, probabilities}`; result cached 6h
- [ ] `PREDICTION_SERVING_BACKEND=sagemaker` → `/predict/AAPL` routes to SageMaker endpoint with identical response shape
- [ ] `ruff`, `pytest`, `checkov`, `tfsec` all green in CI

---

## ADRs

- [ADR 006 — Champion Model Delivery (S3 bootstrap)](./adr/006-champion-model-delivery.md)
- [ADR 007 — Removal of Phantom `BEDROCK_API_KEY`](./adr/007-bedrock-secret-removal.md)
- [ADR 008 — Terraform Remote State](./adr/008-terraform-remote-state.md)
- [ADR 009 — ECS ARM64 Build](./adr/009-ecs-arm64-build.md)
