# ADR 009: Build Fargate Image for ARM64 (`linux/arm64`)

**Date:** 2026-07-08
**Status:** Accepted
**Phase:** 5 — Production Deployment

## Context

`terraform/ecs.tf:43-46` forces `cpu_architecture = "ARM64"` on the Fargate task (Graviton — cheaper, better price/performance). However, `backend/Dockerfile` uses `python:3.14-slim` (and a Rust `maturin` build stage) which builds **amd64 by default** on most CI runners (GitHub-hosted x64 Linux). An amd64 image pushed to ECR and scheduled on an ARM64 task will fail to start (exec format error) — a silent, late-breaking deploy failure.

## Decision

Build and push the backend image with `--platform linux/arm64` (and emit a matching ECR manifest) in the CI deploy pipeline (plan Round 6) and in any manual `docker build`. The Dockerfile remains architecture-agnostic; the platform is a **build-time** switch, not a code change. For local dev, amd64 is fine (Docker Desktop emulates), but the ECR-pushed artifact must be ARM64.

## Rationale

- The ECS task def pins ARM64; the image arch must match or the task never reaches `RUNNING`.
- Graviton Fargate is ~20% cheaper than equivalent x86 for comparable vCPU/RAM — the cost brief ($50/mo budget) benefits.
- `maturin` produces a platform-specific wheel; building on ARM64 (or cross-compiling with the correct `--platform`) is the only correct path. If the CI runner is x86, `maturin` must build for the `aarch64` target (e.g. `maturin build --target aarch64-unknown-linux-gnu` inside an emulated/`--platform` build).

## Consequences

- CI deploy job must run `docker buildx build --platform linux/arm64` (buildx with QEMU emulation, or a native ARM runner).
- The features-engine Rust wheel is compiled for `aarch64` so it loads inside the ARM64 container.
- A mismatch is caught immediately at first `ECS deploy` / `aws ecs run-task` smoke test (documented in plan verification).

## Alternatives Considered

| Alternative              | Reason Rejected                                                                           |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| Switch ECS to x86_64     | More expensive; contradicts the deliberate ARM64 choice in ecs.tf                         |
| Multi-arch manifest list | Heavier CI (build both); only ARM64 is ever scheduled, so single-arch ARM64 is sufficient |
| Emulate at runtime       | Not possible — Fargate schedules a real arch; emulation is build-time only                |
