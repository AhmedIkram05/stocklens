# Remediation status — 2026-11-27

All CRITICAL findings from `docs/CODE-REVIEW-2026-11-16.md` are closed.

## Open

| Item   | Type      | Why it is still open                                                                                                                                    |
| ------ | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| INF-H1 | HIGH, ops | Production state holds `environment=dev` resources including RDS. Needs the state-move maintenance window in `docs/runbooks/INF-H1-state-migration.md`. |

| ML-H4 (ensemble half) | HIGH, design | Registry version is the seed-0 reference; serving blends five. Needs an ensemble artifact design. |
| ML-M8 | MEDIUM, design | S3 publish is per-object; atomic cutover needs a pointer/tar-only layout. |
| ML-M1 | MEDIUM, perf | HPO rebuilds the dataset per threshold candidate. |
| ML-M10 | MEDIUM, perf | Array fill is in place; the Record/list materialisation remains. |
| 12 unnumbered LOW bullets | LOW | Environment/CI hygiene; see the review's LOW tables. |

## Deferred by decision

- INF-H3 (TLS): blocked on a domain/ACM certificate; the `enable_https` path is gated.
- History rewrite for the leaked credentials: values were rotated; rewriting 1,359 SHAs would break forks/PRs for no security gain.

## Verification

CI runs the backend, frontend, Rust, Docker, Airflow, IaC, secret, and CodeQL checks on every PR; each batch above merged only on 15/15 green.

INF-M25 is code-ready behind `enable_private_networking` (default false). Enabling it in production is a deploy-time decision; Bedrock, Yahoo Finance and LangSmith still need NAT/egress or per-service endpoints.
