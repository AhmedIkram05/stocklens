# StockLens — Remediation Log

Running record of the work that closed `docs/CODE-REVIEW-2026-11-16.md`.
The review itself is the findings register; this is what actually shipped.

| Batch                              | PR   | Findings closed                                                                    |
| ---------------------------------- | ---- | ---------------------------------------------------------------------------------- |
| Credential containment             | #367 | FE-C1, INF-C1, INF-C3, INF-H7, INF-M24                                             |
| Auth hardening                     | #369 | BE-C2, BE-C3, BE-M13                                                               |
| Migration truth                    | #370 | BE-C4, BE-C6, BE-M15, BE-L19                                                       |
| MCP dead path                      | #371 | BE-L18, BE-L24                                                                     |
| Currency / FX                      | #373 | BE-D2, BE-D11, BE-D12, BE-M27, BE-L38                                              |
| Newest-N queries                   | #374 | BE-D3, BE-D7                                                                       |
| Performance series                 | #375 | BE-D1, BE-D9, BE-D10, BE-M31, BE-M32                                               |
| Prediction off-loop                | #376 | BE-D14                                                                             |
| JSONB encoding                     | #377 | BE-D13                                                                             |
| Backend runtime                    | #378 | BE-C1, BE-C5, BE-C7, BE-M12, BE-M14, BE-L16, BE-L17, BE-L22                        |
| GraphQL / MCP / receipts endpoints | #380 | BE-M8, BE-M9, BE-M10, BE-M11, BE-L20, BE-L21, BE-D4, BE-D5, BE-M35                 |
| MCP body bound                     | #381 | follow-up to BE-M9 / BE-L20                                                        |
| Drift / market                     | #382 | BE-D6, BE-M16, BE-M17, BE-M20, BE-M21, BE-M36, BE-L46, BE-L47                      |
| Agent tools                        | #383 | BE-D8, BE-D15, BE-M25, BE-M26, BE-M28, BE-M29, BE-M30, BE-M34                      |
| Frontend money / session           | #384 | FE-C2, FE-C3, FE-H5, FE-H6, FE-H7, FE-H14, FE-H16, FE-M39, FE-M40, FE-M41          |
| ML / Airflow critical              | #385 | ML-C1, ML-C2, ML-H1, ML-H6, ML-M11, ML-M12, ML-M14, ML-M15, INF-C2                 |
| Infra security                     | #386 | INF-H2, INF-H9, INF-H10, INF-M1, INF-M3, INF-M4, INF-M26                           |
| Frontend device security           | #387 | FE-H11, FE-H12, FE-H13, FE-M32, FE-M33, FE-M43                                     |
| ML image runtime                   | #388 | ML-C3, ML-H5                                                                       |
| Frontend projections               | #389 | FE-H8, FE-H9, FE-H10, FE-H15, FE-H17, FE-M37                                       |
| Receipts validation                | #390 | BE-M18, BE-M22, BE-M24, BE-L40, BE-L41, BE-L45, BE-L48                             |
| Frontend polling / error           | #391 | FE-M19, FE-M20, FE-M21, FE-M22, FE-M23, FE-M24, FE-M25, FE-M38                     |
| Frontend cleanup                   | #392 | FE-M34, FE-M35, FE-M36, FE-M42, FE-M45, FE-M46, FE-M47, FE-L54, FE-L55, FE-L56     |
| ML promotion                       | #393 | ML-H2, ML-M6, ML-L20, ML-H4 (race half)                                            |
| Backend cleanup                    | #394 | BE-L43, BE-L42, BE-L44, BE-L25                                                     |
| Frontend tail                      | #395 | FE-M44, FE-L50, FE-L51, FE-L53, FE-L57, FE-L48 (partial)                           |
| ML cleanup                         | #396 | ML-M13, ML-M3, ML-M4, ML-L21, ML-L23, ML-L24                                       |
| Infra final                        | #397 | INF-M11, INF-M12, INF-M13, INF-M6, INF-M7, INF-M23                                 |
| Infra high                         | #398 | INF-H4, INF-H5, INF-H6                                                             |
| Backend leftovers                  | #399 | BE-M19, BE-M33, BE-C1 (user keying)                                                |
| Frontend tail 2                    | #400 | FE-H18, FE-M28, FE-M29, FE-M30                                                     |
| ML leftovers                       | #401 | ML-M2, ML-M5, ML-M7, ML-L22, ML-L27                                                |
| Security tail                      | #402 | BE-L23, FE-L52                                                                     |
| Infra tail                         | #411 | budget guard, ECR immutability, dev tfvars, Node 22, log retention, Trivy/validate |
| Dead schemas                       | #412 | BE-L39                                                                             |
| OCR + request bounds               | #413 | BE-M23, FE-M31                                                                     |
| Infra runtime                      | #414 | INF-M2, INF-M10, INF-M8, INF-M9, INF-M15                                           |
| ML dead code / docs                | #415 | ML-L17, ML-L18, ML-L32 (partial)                                                   |
| Frontend dead code                 | #416 | FE-L48 (partial)                                                                   |
| Final backend/frontend cleanup     | #417 | BE-L37, ML-L30                                                                     |
| CI pins / eval runtime             | #418 | CI LOW: action pinning, eval PG18, uv frozen, matrix key, eval timeout             |
| Docs close-out                     | #419 | Remaining/deferred ledger, plan contract                                           |
| Repo hygiene                       | #420 | compose pins, stale mocks, receipt source, uuid type                               |
| WS subscription cap                | #421 | BE-M8 (per-socket cap), INF-H1 runbook, FE-L49 note                                |
| ML array fill                      | #422 | ML-M10 (first step)                                                                |
| CI runner bounds                   | #423 | deploy timeouts, eval Python 3.13, compose password                                |

## Deliberately deferred

| Finding               | Why                                                                                                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| INF-H1                | The production state already contains `environment=dev` resources, including RDS. A name flip replaces the database; it needs a state migration in a maintenance window. |
| INF-H3                | No domain/ACM certificate. The `enable_https` path is gated until one exists.                                                                                            |
| ML-H4 (ensemble half) | The registry version is still the seed-0 reference; serving blends five. Registering the whole ensemble as one artifact is a design change.                              |
| ML-M8                 | S3 publish is still per-object; making it atomic needs a pointer/tar-only cutover.                                                                                       |

## What remains

| Item                      | State                                                                                                |
| ------------------------- | ---------------------------------------------------------------------------------------------------- |
| ML-H4 (ensemble half)     | Deferred design change: registry version is the seed-0 reference; serving blends five.               |
| ML-M8                     | Deferred: per-object publish is correct but not atomic; needs a pointer/tar-only cutover.            |
| ML-M1 / ML-M10            | HPO rebuilds the dataset per threshold candidate; fetch materialises every row before conversion.    |
| INF-H1                    | Deferred to a maintenance window: production state holds `environment=dev` resources, including RDS. |
| INF-M25                   | Production tasks still use public subnets; needs private subnets + VPC endpoints.                    |
| BE-M8                     | Per-client WS metering exists; no per-socket subscription cap.                                       |
| FE-L49                    | Theme tokens are computed at module load and do not rescale on rotation.                             |
| 12 unnumbered LOW bullets | Mostly environment/CI hygiene; see the review's LOW sections.                                        |
