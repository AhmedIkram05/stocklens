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
   - [Round 4 — AWS Budgets + Cost Anomaly](#round-4--aws-budgets--cost-anomaly)
   - [Round 5 — MLflow + Airflow Productionization (P1–P6)](#round-5--mlflow--airflow-productionization-p1p6)
   - [Round 6 — CI/CD Deploy Pipeline (OIDC)](#round-6--cicd-deploy-pipeline-oidc)
   - [Round 7 — SageMaker Optional Serving Path](#round-7--sagemaker-optional-serving-path)
   - [Round 8 — Polish, Tests & Verification](#round-8--polish-tests--verification)
5. [Testing Strategy](#testing-strategy)
6. [Success Criteria](#success-criteria)
7. [Risks & Mitigations](#risks--mitigations)
8. [Verification Checklist](#verification-checklist)
9. [ADRs](#adrs)

---

## Overview

Phase 5 migrates StockLens from local Docker Compose to a production AWS deployment. The Phase 4 serving path (`GET /predict/{ticker}`, lifespan-loaded `GlobalLSTM`, 6h Redis result cache, `prediction_log` drift writes) is **reused as-is** — the only serving change is _where the champion model comes from_ (Round 2). The bulk of Phase 5 is infrastructure: harden Terraform, add HTTPS/WAF/auto-scaling/observability/budgets, productionize MLflow + Airflow, and add a CI/CD deploy pipeline.

### Reality Audit (verified against code, not filenames)

| Deliverable (from MASTER_PLAN)                      | Status      | Evidence                                                                    |
| --------------------------------------------------- | ----------- | --------------------------------------------------------------------------- |
| `/predict` endpoint (champion, 6h Redis cache)      | ✅ EXISTS   | `backend/src/prediction/router.py:34`, `service.py:40`, `config.py:48`      |
| Redis 6h result cache                               | ✅ EXISTS   | `router.py:31,117`; `config.py:48` (`PREDICTION_CACHE_TTL=21600`)           |
| `prediction_log` drift writes                       | ✅ EXISTS   | `backend/src/prediction/prediction_logger.py`                               |
| Load champion **from MLflow** at runtime            | ❌ MISSING  | runtime loads local `.pt`; no `import mlflow` in `backend/src/`             |
| Champion artifact **delivery into Fargate**         | ❌ MISSING  | image only `mkdir /model_artifacts/champion` (empty)                        |
| SageMaker serverless path                           | ❌ MISSING  | zero references anywhere in repo                                            |
| Terraform VPC/RDS/S3/ECR/Redis/IAM/ECS/ALB/Secrets  | ✅ MOSTLY   | root `.tf` + modules                                                        |
| ALB **HTTPS + WAF**                                 | ❌ MISSING  | HTTPS commented `ecs.tf:200-212`; WAF module = TODO, not invoked            |
| ACM                                                 | ❌ MISSING  | none                                                                        |
| ECS Auto Scaling (CPU + request count)              | ❌ MISSING  | only `desired_count=2` var                                                  |
| CloudWatch alarms + dashboard                       | ❌ MISSING  | `modules/monitoring` skeleton, not invoked                                  |
| AWS Budgets + Cost Anomaly ($50)                    | ❌ MISSING  | none                                                                        |
| Secrets injected (DB, JWT, REDIS) no `.env`         | ⚠️ PARTIAL  | only DB+JWT injected; `REDIS_PASSWORD` not wired; `BEDROCK_API_KEY` phantom |
| CI: ruff→pytest→checkov→tfsec→docker→ECR→ECS (OIDC) | ❌ MISSING  | only lint/type/test/codeql                                                  |
| Remote Terraform state                              | ❌ DISABLED | `backend "s3"` commented `main.tf:36-42`                                    |

### Key Deliverables

1. **Remote Terraform state** — S3 + DynamoDB lock before prod apply (ADR 008).
2. **HTTPS + WAF** — ACM cert, ALB HTTPS listener (200/min/IP rate limit + SQLi/XSS managed rules), WAF associated to ALB.
3. **Champion delivery** — training/Airflow publishes `.pt` to S3; Fargate startup bootstrap downloads it; `load_model` unchanged (ADR 006).
4. **Redis auth** — inject `REDIS_PASSWORD`, build `REDIS_URL` with auth (was passed plaintext, no token).
5. **`.env` guard** — prod ECS task ships no `.env`; `config.py` env_file default overridden.
6. **RDS Multi-AZ** — flip `multi_az=false→true` in production (always on; user directive — production is the only environment, no dev/staging).
7. **Auto scaling** — `aws_appautoscaling` target tracking CPU% + request count.
8. **Observability** — CloudWatch alarms + dashboard (p50/p95/p99 latency, error rate, RDS conns, ECS CPU/mem) + SNS + drift metric filter.
9. **Cost control** — Budgets ($50/mo) + Cost Anomaly monitors.
10. **MLflow + Airflow prod** — backends → RDS PostgreSQL, metadata → RDS, split scheduler/webserver, IAM/KMS (Compatibility Tracker P1–P6).
11. **CI/CD deploy** — OIDC: ruff→pytest→checkov+tfsec→docker `--platform linux/arm64`→ECR→terraform→ECS rolling (ADR 009).
12. **SageMaker optional** — config-gated stretch serving path.

---

## Architecture (Target End State)

```
                        ┌─────────────┐
   Internet ──HTTPS────►│  ACM Cert   │
                        └──────┬──────┘
                               │
                        ┌──────▼──────┐   rate 200/min/IP + SQLi/XSS
                        │  ALB (HTTPS)│◄──────── WAF v2 Web ACL
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
     │ MLflow + Airflow (RDS metadata)            │ bootstrap download
     │ (separate ECS/EC2)                          │ champion .pt

  CI/CD (GitHub Actions, OIDC):
     ruff → pytest → checkov+tfsec → docker --platform linux/arm64 → ECR → terraform (remote state) → ECS rolling deploy
```

---

## Modules Touched

```
terraform/
├── main.tf                      # MODIFY: uncomment backend s3; wire waf + monitoring modules
├── variables.tf                 # MODIFY: add acm_domain, waf_rate_limit, autoscale vars, budget_amount
├── outputs.tf                   # MODIFY: add waf_arn, dashboard_url, budget_name
├── ecs.tf                       # MODIFY: secrets REDIS_PASSWORD; REDIS_URL w/ auth; HTTPS; entrypoint bootstrap; Multi-AZ n/a here
├── rds.tf                       # MODIFY: multi_az = true (production)
├── acm.tf                       # NEW: aws_acm_certificate + validation
├── waf.tf (or modules/waf)      # NEW: aws_wafv2_web_acl (rate + SQLi/XSS), associate ALB
├── autoscaling.tf               # NEW: appautoscaling target + policies
├── monitoring.tf                # NEW: alarms + dashboard + SNS topic
├── budgets.tf                   # NEW: aws_budgets_budget + ce_anomaly_monitor
├── iam.tf                       # MODIFY: champion S3 GetObject; OIDC provider
└── security_groups.tf           # MODIFY: alb_https ingress

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

**Objective:** Make the Terraform root production-safe before any apply: enable remote state, remove the phantom `BEDROCK_API_KEY`, wire Redis auth, guard `.env`, enable Multi-AZ, and lay HTTPS/ACM/WAF/observability wiring stubs.

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

   Add `tf_state_bucket` and `tf_state_lock_table` vars (with defaults) in `variables.tf`. Create the bucket + DynamoDB table **out-of-band** (one-time bootstrap apply), then `terraform init -reconfigure`.

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

6. **HTTPS + ACM + WAF + champion bucket (fully implemented in R1, not stubbed).** Round 1 must produce real resources, not invocations of empty skeletons:
   - **ACM** — new `terraform/acm.tf`:
     ```hcl
     resource "aws_acm_certificate" "api" {
       domain_name       = var.api_domain
       validation_method = "DNS"
       lifecycle { create_before_destroy = true }
     }
     resource "aws_route53_record" "api_validation" {
       for_each = { for d in aws_acm_certificate.api.domain_validation_options : d.domain_name => d }
       zone_id = var.route53_zone_id
       name    = each.value.resource_record_name
       type    = each.value.resource_record_type
       records = [each.value.resource_record_value]
       ttl     = 60
     }
     resource "aws_acm_certificate_validation" "api" {
       certificate_arn         = aws_acm_certificate.api.arn
       validation_record_fqdns = [for r in aws_route53_record.api_validation : r.fqdn]
     }
     ```
     Cert must validate (implicit dep) before the HTTPS listener applies.
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
   - **HTTPS listener** — in `ecs.tf` uncomment the HTTPS listener (lines 200–212), `certificate_arn = aws_acm_certificate_validation.api.certificate_arn`, `default_action { type = "forward" }`.
   - **443 ingress (explicit step)** — in `security_groups.tf`, add to the ALB security group:
     ```hcl
     ingress { from_port = 443; to_port = 443; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"]; description = "HTTPS from internet" }
     ```
   - **Champion bucket + var** — the S3 `mlflow-artifacts` bucket (already in `modules/s3`) is the champion source. Add `variable "mlflow_artifacts_bucket" { default = "stocklens-mlflow-artifacts" }` and enable **versioning** on that bucket (last-known-good fallback if a bad champion is published — see Risk: SPOF). `CHAMPION_S3_URI` (Round 2) = `s3://${var.mlflow_artifacts_bucket}/champion`.
   - **Monitoring module body** — create `modules/monitoring` `main.tf`/`variables.tf` skeleton in R1 (so `module "monitoring"` resolves); Round 3 populates its alarms/dashboard vars.
   - **Orphan secret** — `secrets.tf` currently provisions `bedrock_model_id` as a Secrets Manager secret but it is injected as a plain `environment` var (`ecs.tf:96-98`) and never read as a secret. Remove the `bedrock_model_id` secret resource (keep the plain `BEDROCK_MODEL_ID` env). Re-confirm no `BEDROCK_API_KEY` exists (ADR 007).
   - In `main.tf`, wire `module "waf"` (inputs `alb_arn`, `waf_rate_limit`) and `module "monitoring"` (inputs TBD in R3).

**Verify:**

```bash
cd terraform && terraform init -reconfigure && terraform validate && terraform plan
```

- No `BEDROCK_API_KEY` references in `terraform/` or `backend/`.
- `terraform plan` shows `aws_db_instance` `multi_az = true` (production).
- `checkov -d . --quiet` passes (WAF `CKV_AWS_272` skip can be removed now that `aws_wafv2_web_acl` exists; ACM `CKV_AWS_103` etc. satisfied).
- `terraform plan` shows `aws_wafv2_web_acl` + `aws_wafv2_web_acl_association` (ALB), `aws_acm_certificate` + validation, ALB 443 ingress, `modules/monitoring` resources, and `mlflow-artifacts` bucket versioning enabled.

**Edge Cases:**

- Remote-state bootstrap: the bucket + lock table cannot use the remote backend — apply them with a separate minimal config first, or `aws s3 mb` + `aws dynamodb create-table` via CLI.
- ACM DNS validation requires the domain's Route53 hosted zone; if using a non-Route53 registrar, fall back to email validation and note the manual step.
- `rediss://` (TLS) is required because ElastiCache forces in-transit encryption — plain `redis://` will reject auth.

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

   S3 **versioning** on the `mlflow-artifacts` bucket (Round 1) gives a last-known-good fallback: if a bad champion is published, revert the `champion/` prefix to the prior version before the next deploy. Add a CloudWatch alarm on bootstrap `exit 1` (non-zero task exit) so a model-delivery outage pages.

3. **Dockerfile entrypoint + ARM64 wheel (ADR 009 / M1).** In `backend/Dockerfile`:

   ```dockerfile
   COPY docker/bootstrap.py /usr/local/bin/bootstrap.py
   ENTRYPOINT ["python", "/usr/local/bin/bootstrap.py"]
   CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
   ```

   The Rust features-engine wheel must be **`aarch64`**, not the default amd64, or it import-crashes inside the ARM64 container (QEMU only emulates the final image, not the compiled `.so`). Pin the maturin build stage: `maturin build --release --target aarch64-unknown-linux-gnu` (or set `ENV CARGO_BUILD_TARGET=aarch64-unknown-linux-gnu`). The `docker buildx build --platform linux/arm64` in Round 6 then produces a consistent ARM64 image.

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

**Objective:** Target-tracking auto scaling (CPU + request count) and CloudWatch alarms + dashboard (p50/p95/p99 latency, error rate, RDS conns, ECS CPU/mem) with SNS alerting and a drift metric filter.

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
   # + request-count policy (ECSServiceAverageRequestCount, target ~var.ecs_rps_target)
   ```

2. **Monitoring.** New `monitoring.tf`:
   - `aws_sns_topic` `stocklens-alerts` + `aws_sns_topic_subscription` (email from `var.billing_alert_email`). **Required human step:** the subscriber must click the SNS confirmation email before alerts deliver — note this as a manual gate, not an automated step.
   - Alarms: ECS CPU > 80%, ECS memory > 80%, ALB 5xx > threshold, ALB target 4xx rate, RDS free storage < 10%, RDS connections > 80% `max_connections`.
   - Latency p50/p99: `aws_cloudwatch_metric_alarm` on `AWS/ApplicationELB` `TargetResponseTime` with `extended_statistic` "p99" (CloudWatch natively emits p50/p90/p99 for `TargetResponseTime` — **not** p95; if a literal p95 widget is required, build it via CloudWatch metric-math, not the raw statistic). Enable ALB access log emission to the existing ALB log bucket so the statistic is populated.
   - Dashboard `aws_cloudwatch_dashboard` with widgets: latency p50/95/99, HTTP 2xx/4xx/5xx, ECS CPU/mem, RDS connections, Redis CPU.
   - Drift alert metric filter: `aws_cloudwatch_log_metric_filter` on the existing structlog drift alert (`"drift_alert"` / `alert_triggered=true`) → custom metric → alarm → SNS (reuses Phase 4 drift alert log line).

**Verify:**

```bash
terraform plan   # shows appautoscaling + 8 alarms + 1 dashboard + SNS
aws cloudwatch get-dashboard --dashboard-name stocklens-prod
```

- Manually scale test: `aws ecs update-service --desired-count 1` then generate load → desired count climbs toward `max_capacity`.

**Edge Cases:**

- `min_capacity` must be ≥ 2 for HA (AZ spread); `max_capacity` bounded by `$50/mo` budget — pick 2→6.
- p99 latency needs ALB access logs enabled; without them the statistic is absent (dashboard widget blank).
- SNS email subscription requires confirmation click — automate via var or note manual confirm.

---

### Round 4 — AWS Budgets + Cost Anomaly

**Objective:** $50/mo guardrail + anomaly detection on RDS/ECS.

**Files:** `terraform/budgets.tf`, `terraform/variables.tf`

**Steps:**

```hcl
resource "aws_budgets_budget" "monthly" {
  name         = "stocklens-monthly"
  budget_type  = "COST"
  limit_amount = var.budget_monthly_amount   # "50"
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

**Verify:** `terraform plan` shows budget + anomaly monitor/subscription. Trigger a test anomaly alert (optional, costs money — skip in CI).

**Edge Cases:** Anomaly monitors need ~1 day of billing history before they fire; cannot verify same-day. Budget 80% notification is the practical early-warning.

---

### Round 5 — MLflow + Airflow Productionization (Compatibility Tracker P1–P6)

**Objective:** Move MLflow + Airflow off SQLite/local-state to production-grade (RDS PostgreSQL metadata, S3 artifact store, IAM/KMS, split scheduler/webserver). Addresses TRACKER Compatibility P1–P6.

**Files:** `airflow/` (docker-compose, Dockerfile, config), `backend/ml/config.py`, `terraform/` (new `mlflow.tf` + Airflow ECS/EC2 module or `EcsRunTaskOperator` wiring), `backend/src/config.py`

**Steps:**

- **P1 (Airflow → Backend network):** Backend DB reachable from Airflow; Airflow uses `DATABASE_URL` (prod) instead of local postgres. Same VPC/private subnets + SG allow.
- **P2 (Shared model volumes → S3/EFS):** Champion + artifacts use S3 (`mlflow-artifacts`) — Round 2 already publishes there. Remove local volume mounts.
- **P3 (Airflow SQLite → RDS) + MLflow backend store:** New `terraform/mlflow.tf` creates an RDS-backed MLflow tracking store — point `MLFLOW_TRACKING_URI` (training side, `backend/ml/config.py`) at `postgresql://<rds>/mlflow` (separate `mlflow` database/schema on the existing RDS instance, or a small dedicated `db.t4g.micro`). This retires the SQLite MLflow backend so the `champion` registry alias is durable (currently SQLite). Airflow: `AIRFLOW__CORE__SQL_ALCHEMY_CONN = postgresql://...` (RDS). `airflow db migrate` on first boot (never `initdb` on upgrade).
- **P4 (ML container → ECS RunTask):** Wrap `ml.pipeline` as an ECS task invoked via `EcsRunTaskOperator` (or keep Airflow on a small EC2 t3.medium with the backend image, per Phase 4 design). Decide: keep Airflow-hosted container (simpler) vs EcsRunTaskOperator (cleaner separation). Primary = Airflow container on EC2 referencing RDS + S3; `EcsRunTaskOperator` is optional stretch.
- **P5 (S3 IAM/KMS):** Airflow + backend task/instance roles get scoped S3 + KMS access. Concretely, add to `terraform/airflow.tf` (or `iam.tf`):
  ```hcl
  resource "aws_iam_role" "airflow" {  # EC2 instance profile OR ECS task role
    assume_role_policy = jsonencode({
      Version = "2012-10-17"
      Statement = [{ Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" }, Effect = "Allow" }]
    })
  }
  resource "aws_iam_role_policy" "airflow_s3_kms" {
    role = aws_iam_role.airflow.id
    policy = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
          Resource = [aws_s3_bucket.mlflow_artifacts.arn, "${aws_s3_bucket.mlflow_artifacts.arn}/*",
                      aws_s3_bucket.drift_reports.arn, "${aws_s3_bucket.drift_reports.arn}/*"] },
        { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"],
          Resource = [aws_kms_key.s3.arn] }
      ]
    })
  }
  ```
  Reuse the same policy pattern for the backend task role (add `s3:GetObject` on `champion/*` only — see R2). The SSE-KMS key (`aws_kms_key.s3`) is created in `modules/s3` or `security_groups.tf`; bucket policy enforces `aws:SecureTransport` + `s3:x-amz-server-side-encryption:aws:kms`.
- **P6 (CloudWatch alerting):** Airflow + MLflow log to CloudWatch (already awslogs in ECS; for EC2, install CloudWatch agent). Drift alert filter from Round 3 covers drift.

**Verify:** `airflow dags list` shows `weekly_retraining`; one manual DAG run promotes champion → S3 → next Fargate deploy serves new model.

**Edge Cases:**

- RDS PostgreSQL for Airflow metadata requires `airflow db migrate` (not `initdb`) on upgrade.
- MLflow backend store also → RDS PostgreSQL (`backend/sqlalchemy` backend) so the registry `champion` alias is durable (currently SQLite). Update `MLFLOW_TRACKING_URI` to `postgresql://...`.
- Single-container LocalExecutor is fine for weekly cadence; only move to Celery/workers if retraining overlaps (it doesn't — DAG sequences tasks).

---

### Round 6 — CI/CD Deploy Pipeline (OIDC)

**Objective:** GitHub Actions OIDC deploy: ruff → pytest → checkov+tfsec → docker `--platform linux/arm64` → ECR → terraform (remote state) → ECS rolling. No long-lived AWS keys.

**Files:** `.github/workflows/deploy.yml`, `terraform/iam.tf` (OIDC provider)

**Steps:**

1. **OIDC provider.** In `iam.tf` add `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com`, plus a deploy role whose trust policy pins the **repo + branch** so no other repo/branch can assume it:

   ```hcl
   resource "aws_iam_openid_connect_provider" "github" {
     url             = "https://token.actions.githubusercontent.com"
     client_id_list  = ["sts.amazonaws.com"]
     thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]  # GitHub OIDC thumbprint
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
         values   = ["repo:owner/stocklens:ref:refs/heads/main"]
       }
     }
   }
   resource "aws_iam_role" "deploy" {
     name               = "stocklens-github-deploy"
     assume_role_policy = data.aws_iam_policy_document.github_oidc_assume.json
     # attach: ECR push, ECS deploy, terraform state bucket rw, KMS, pass-role
   }
   ```

   Replace `owner/stocklens` with the real GitHub org/repo. Reference `aws_iam_role.deploy.arn` in `outputs.tf` as `ecs_deploy_role_arn` (consumed by `deploy.yml` via `secrets.ECS_DEPLOY_ROLE_ARN`).

2. **Deploy workflow** `.github/workflows/deploy.yml`:
   ```yaml
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - run: ruff check backend/ && ruff format --check backend/
         - run: cd backend && pytest -q
     iac-scan:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: bridgecrewio/checkov-action@master
           with: { directory: terraform/ }
         - run: tfsec terraform/   # install via aquasecurity/tfsec-action
     build-push:
       runs-on: ubuntu-latest
       steps:
         - uses: aws-actions/configure-aws-credentials@v4
           with: { role-to-assume: ${{ secrets.ECS_DEPLOY_ROLE_ARN }}, aws-region: eu-west-2 }
         - uses: docker/setup-buildx-action@v3
          - run: cd backend && docker buildx build --platform linux/arm64 -f backend/Dockerfile -t $ECR_URL:${{ github.sha }} --push .
            # explicit backend/ context + Dockerfile path (ADR 009); QEMU via setup-qemu-action
     deploy:
       needs: [test, iac-scan, build-push]
       environment: production   # requires manual approval
       steps:
         - uses: aws-actions/configure-aws-credentials@v4
           with: { role-to-assume: ${{ secrets.ECS_DEPLOY_ROLE_ARN }}, aws-region: eu-west-2 }
         - run: cd terraform && terraform init && terraform apply -auto-approve
         - run: aws ecs update-service --cluster stocklens --service api --force-new-deployment
   ```

**Verify:** Push to `Phase-5/Planning` → `deploy.yml` runs; ECR gets an `arm64` image; `terraform apply` uses remote state; ECS force-new-deployment pulls new task (bootstrap downloads champion). Manual approval gate on `production` env.

**Edge Cases:**

- `docker buildx --platform linux/arm64` on x86 runners needs QEMU (`docker/setup-qemu-action`) OR a native ARM runner. The `maturin` Rust wheel must be `aarch64` (ADR 009).
- OIDC subject condition must pin the repo + branch to avoid cross-repo assumption.
- `terraform apply` in CI must use the same remote state bucket as humans (Round 1) — single source of truth.

---

### Round 7 — SageMaker Optional Serving Path

**Objective:** Config-gated alternate inference route (`PREDICTION_SERVING_BACKEND = fargate | sagemaker`). Primary remains Fargate. This is a **stretch** round — only if SageMaker is desired.

**Files:** `backend/src/config.py`, `backend/src/prediction/router.py` (optional branching), `terraform/sagemaker.tf` (optional)

**Steps:**

- Add `PREDICTION_SERVING_BACKEND: str = os.getenv("PREDICTION_SERVING_BACKEND", "fargate")` to `config.py`.
- In `service.py`, if `sagemaker`, invoke `boto3` `sagemaker-runtime` `InvokeEndpoint` instead of local `GlobalLSTM`. Default path unchanged.
- Optional `terraform/sagemaker.tf`: serverless inference config pointing at the same champion model artifact (packaged as SageMaker model).

**Verify:** With `PREDICTION_SERVING_BACKEND=sagemaker`, `/predict` routes to endpoint; default `fargate` behaviour identical to R1–R6.

**Edge Cases:** SageMaker serverless cold start adds latency; only worthwhile if on-demand scaling of inference is needed. Keep Fargate primary — SageMaker is optional per MASTER_PLAN.

---

### Round 8 — Polish, Tests & Verification

**Objective:** End-to-end verification, drift S3 bucket Terraform-managed (currently deferred), ruff clean, docs updated.

**Steps:**

- Ensure `stocklens-drift-reports` S3 bucket is created via Terraform (currently referenced in config but bucket creation deferred to Phase 5 — add to `modules/s3` or `rds.tf`/s3 module).
- Run full `ruff check backend/`, `pytest backend/`, `checkov -d terraform/`, `tfsec terraform/`.
- Deploy to production, smoke test `/health`, `/predict/AAPL`, drift endpoint, dashboard renders.
- Update `docs/CONTEXT.md` (Production Deployment glossary) and `docs/TRACKER.md` Phase 5 (Step Tracker + Deviations + Verification).
- Mark `BEDROCK_API_KEY` removed in MASTER_PLAN/TRACKER (ADR 007).

**Verify:** [Verification Checklist](#verification-checklist) all green.

---

## Testing Strategy

| Layer         | Test                                                              | Command                                        |
| ------------- | ----------------------------------------------------------------- | ---------------------------------------------- |
| Config        | `REDIS_URL` builds with auth; `.env` skipped in production        | `pytest backend/tests/test_config.py`          |
| Bootstrap     | champion download succeeds / fails-fast on missing bucket         | unit test `docker/bootstrap.py` (mocked boto3) |
| Serving       | `/predict/{ticker}` returns correct shape with S3-delivered model | `pytest backend/tests/test_prediction.py`      |
| IaC           | `terraform validate` + `checkov` + `tfsec` clean                  | CI `iac-scan` job                              |
| Deploy (prod) | ALB HTTPS 200, WAF blocks >200 req/min/IP, p95 latency dashboard  | manual smoke + `curl` loop                     |
| Drift alert   | structlog drift alert → CloudWatch metric → SNS                   | inject test drift log line                     |

---

## Success Criteria

1. `GET /predict/{ticker}` serves from a champion model delivered via S3 bootstrap on a stateless Fargate task (no baked-in `.pt`, no MLflow runtime dep).
2. All traffic is HTTPS behind an ACM cert; WAF enforces 200 req/min/IP + SQLi/XSS.
3. Redis is authenticated (`rediss://` + `REDIS_PASSWORD`); no `.env` in prod.
4. ECS auto-scales on CPU + request count; CloudWatch dashboard shows p50/p95/p99 + error rate + RDS/ECS health; SNS alerts fire.
5. Monthly budget $50 with 80% alert; Cost Anomaly monitor active.
6. MLflow + Airflow run on RDS PostgreSQL (no SQLite), S3 artifacts, IAM/KMS scoped.
7. CI/CD deploys via OIDC with ruff→pytest→checkov+tfsec→arm64 docker→ECR→terraform→ECS; manual approval on prod.
8. Terraform state is remote (S3 + DynamoDB lock).

---

## Risks & Mitigations

| Risk                                                                                                                                                                                                                                                                                                                     | Mitigation                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| amd64 image on ARM64 task (exec format error)                                                                                                                                                                                                                                                                            | buildx `--platform linux/arm64` (ADR 009); smoke test catches at first deploy                                                                                                                                                                                                   |
| Champion download fails at startup → model-less task                                                                                                                                                                                                                                                                     | bootstrap `exit 1` fast-fail; ECS keeps last good task                                                                                                                                                                                                                          |
| WAF too strict blocks legit traffic                                                                                                                                                                                                                                                                                      | start in CloudWatch metrics-only mode, then enable block after baseline                                                                                                                                                                                                         |
| Remote state lock contention in CI                                                                                                                                                                                                                                                                                       | DynamoDB lock (ADR 008); serialise prod deploy job                                                                                                                                                                                                                              |
| RDS Multi-AZ cost (always on) exceeds $50 budget                                                                                                                                                                                                                                                                         | budget alert + right-size `db.t4g.micro`; Multi-AZ forced ON in production (user directive — prod-only)                                                                                                                                                                         |
| Phantom `BEDROCK_API_KEY` re-added                                                                                                                                                                                                                                                                                       | ADR 007 removes it from docs; CI grep guard                                                                                                                                                                                                                                     |
| Airflow→RDS migration breaks retraining                                                                                                                                                                                                                                                                                  | take an RDS snapshot before `airflow db migrate`; validate on a restored snapshot; `airflow db migrate` not `init` (no staging env exists — prod is the only one)                                                                                                               |
| **Budget $50/mo unrealistic** — Two scopes: **serving stack only** (Multi-AZ RDS + ElastiCache + 2× Fargate 2 vCPU + ALB + NAT + WAF) ≈ **$90–130/mo** at rest; **full prod incl. Airflow (t3.medium) + MLflow (t3.small)** ≈ **$300–400/mo** (per Phase 4 TRACKER note 357). Auto-scaling to 6 tasks blows past either. | Raise the budget threshold to a realistic value (≥$150 serving / ≥$400 full). Multi-AZ forced ON in production (user directive — prod-only). Keep the $50 anomaly alert as an early-warning signal, not a hard cap. Reconcile `MASTER_PLAN.md` line 499's "$50/mo" infra claim. |
| **Champion S3 is a SPOF** — deleted/unreachable `champion/` object → all new tasks fast-fail → total capacity loss                                                                                                                                                                                                       | S3 versioning on `mlflow-artifacts`; bootstrap falls back to **last-known-good** `model.pt` (previous version) when the latest fetch fails; CloudWatch alarm on bootstrap `exit 1` pages on-call.                                                                               |

---

## Verification Checklist

- [ ] `terraform init -reconfigure` uses S3 + DynamoDB (no local `terraform.tfstate` committed)
- [ ] `grep -r BEDROCK_API_KEY terraform/ backend/` → no matches
- [ ] `REDIS_URL` in prod task contains `rediss://:***@` (auth present)
- [ ] `ENVIRONMENT=production` → `config.py` does NOT load `.env`
- [ ] `aws_acm_certificate` issued + validation complete; ALB HTTPS listener 200/OK
- [ ] `aws wafv2` Web ACL associated to ALB; rate rule 200/min/IP; SQLi + XSS managed rule groups present
- [ ] `aws appautoscaling` target + 2 policies created; min 2 / max 6
- [ ] CloudWatch dashboard renders; 8 alarms + SNS subscription confirmed
- [ ] `aws budgets` + `ce_anomaly_monitor` present
- [ ] MLflow + Airflow metadata on RDS PostgreSQL (no SQLite); retraining DAG promotes → S3
- [ ] `deploy.yml` OIDC role assumed; `docker buildx --platform linux/arm64` pushed to ECR
- [ ] `ECS force-new-deployment` → task RUNNING on ARM64 with champion model loaded
- [ ] `/predict/AAPL` returns `{ticker, prediction, confidence, probabilities}`; result cached 6h
- [ ] `ruff`, `pytest`, `checkov`, `tfsec` all green in CI

---

## ADRs

- [ADR 006 — Champion Model Delivery (S3 bootstrap)](./adr/006-champion-model-delivery.md)
- [ADR 007 — Removal of Phantom `BEDROCK_API_KEY`](./adr/007-bedrock-secret-removal.md)
- [ADR 008 — Terraform Remote State](./adr/008-terraform-remote-state.md)
- [ADR 009 — ECS ARM64 Build](./adr/009-ecs-arm64-build.md)
