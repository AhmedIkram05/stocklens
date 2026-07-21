# ADR 008: Terraform Remote State (S3 + DynamoDB) Before Production Apply

**Date:** 2026-07-08
**Status:** Accepted
**Phase:** 5 — Production Deployment

## Context

`terraform/main.tf:36-43` contains a `backend "s3"` block that is **commented out**, leaving state in local `terraform.tfstate`. There is an explicit in-file warning that this is unsafe for production. With the CI/OIDC deploy pipeline (plan Round 6) operating on the single production environment, local state is a real hazard: concurrent applies clobber state, state loss means unrecoverable infrastructure drift, and there is no state locking.

## Decision

Enable a remote `backend "s3"` with:

- `bucket` = a dedicated, versioned, SSE-enabled state bucket (e.g. `stocklens-terraform-state`),
- `key` = `stocklens/production/terraform.tfstate` (single production state file — no other environments exist),
- `region` = `eu-west-2` (matches `AWS_REGION`),
- `dynamodb_table` = `stocklens-terraform-locks` (state locking + consistency),
- `encrypt = true`.

The state bucket and DynamoDB lock table are created **once, out-of-band** (separate bootstrap, or a minimal `tofu/terraform` apply of just those two resources) before any environment `apply`. Remote state is enabled **before** the first production apply and before the CI deploy pipeline goes live.

## Rationale

- Production infra must have durable, locked, auditable state. Local state violates all three.
- DynamoDB locking prevents two CI runs (or a human + CI) from applying simultaneously and corrupting state.
- S3 versioning gives a rollback path if a bad apply corrupts state.
- This is a prerequisite, not an optional extra: the OIDC deploy pipeline (plan Round 6) reads/writes the same state, so remote state must exist first.

## Consequences

- A one-time bootstrap step creates the state bucket + lock table (cannot itself use the remote backend).
- The commented `backend "s3"` block in `main.tf` is uncommented and parameterised (bucket name + table name via variables with sensible defaults).
- `terraform init -reconfigure` is run once to migrate local → remote.
- `.gitignore` already excludes `*.tfstate`; the remote backend makes local state moot.

## Alternatives Considered

| Alternative           | Reason Rejected                                                                      |
| --------------------- | ------------------------------------------------------------------------------------ |
| Terraform Cloud / HCP | Adds external SaaS + account; S3+DynamoDB is already in-stack and free-tier friendly |
| Local state "for now" | Explicitly unsafe per the file's own warning; blocks CI deploy                       |
| Git-backed state      | No locking, no encryption at rest story, fragile                                     |
