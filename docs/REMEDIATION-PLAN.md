# Remediation Plan — 17 Nov → 9 Dec 2026

**Source:** `docs/CODE-REVIEW-2026-11-16.md`
**Baseline:** `main` at `d32c052` (PR #367 merged)
**Status:** approved 2026-11-16. D1 opens this file as a PR; D2 starts the first code batch.

---

## 1. Contract

- **Work unit:** one atomic PR per root cause. A PR may close several finding IDs when they share
  one behavioural intent; the PR body lists every ID it closes.
- **History:** one commit per PR where possible. A second commit is allowed only when CI forces a
  fix; it is budgeted as +1 event.
- **Contribution ceiling:** **42 GitHub contribution events per calendar day**, counting commits
  that land on `main`, PR opens, merge commits, issues, and reviews. Plan to **≤ 21/day**; the
  ceiling is a guardrail, not a target.
- **Merge authority:** the agent pushes the branch and opens the PR; **Ahmed merges**. The agent
  does not hand back a PR until every CI check is green.
- **Review gate:** before a PR is opened, a `code-reviewer` subagent performs a **thorough**
  review of the branch diff against `main` and the acceptance test. **All review findings are
  fixed before the PR is opened**, not just CRIT/HIGH.
- **Definition of done per PR:** code + regression test (unless pure deletion/config) + acceptance
  test passes locally + subagent review clean + CI green + this plan's status row updated.
- **Scope additions:** any regression caused by a fix is fixed in the same PR. Any new issue found
  outside that PR goes to `docs/FIX-DISCOVERIES.md` and is scheduled in the next free slot. A
  GitHub issue is opened only for an item deferred past 9 Dec (each issue costs one event).
- **Out of scope:** dependabot PRs (Ahmed owns them), local Docker/Docker Desktop (never used),
  history rewriting (decided against), and any deploy (`AWS_DEPLOY_ENABLED` stays off).

---

## 2. Locked decisions

| #   | Decision                                                                                                                                                                          |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **TLS:** no domain/ACM cert exists. Add `enable_https` + `domain_name` variables and a gated HTTPS listener; default off. `INF-H3` is **blocked/deferred**, not silently dropped. |
| 2   | **Retention:** receipts 6 years; MLflow artifacts and drift reports 90 days; noncurrent versions 30 days.                                                                         |
| 3   | **SageMaker:** gate the module behind `enable_sagemaker = false`; serving stays `fargate`.                                                                                        |
| 4   | **Redis:** variable-driven node count, HA/failover in production, engine 8.x.                                                                                                     |
| 5   | **RDS:** 7-day dev / 14-day prod backups, Performance Insights on.                                                                                                                |
| 6   | **Network:** dev stays public; production path is private subnets + interface VPC endpoints, no NAT.                                                                              |
| 7   | **WAF:** add `AWSManagedRulesCommonRuleSet`; no Bot Control.                                                                                                                      |
| 8   | **Node:** 22 LTS.                                                                                                                                                                 |
| 9   | **Python:** 3.13 everywhere (CI, images, pyproject).                                                                                                                              |
| 10  | **MLflow:** image upgrades to 3.x; migration tested.                                                                                                                              |
| 11  | **Airflow:** default image becomes 3.x; 3.x import/config paths.                                                                                                                  |
| 12  | **Branch protection:** required status checks on `main` (CI, Secret Scan, CodeQL), no required reviews.                                                                           |
| 13  | **ECR:** immutable tags; drop `-latest`.                                                                                                                                          |
| 14  | **prediction_log:** 90-day retention.                                                                                                                                             |
| 15  | **History:** no rewrite; the incident runbook remains for a future non-rotatable leak.                                                                                            |

---

## 3. Baseline reconciliation

223 findings reviewed. Current status:

| State              |                              Count | IDs                                                                                                                |
| ------------------ | ---------------------------------: | ------------------------------------------------------------------------------------------------------------------ |
| **Fixed by #367**  |            4 unique issues (5 IDs) | `FE-C1` = `INF-C3` (OCR key + gitleaks), `INF-C1` (tfplan), `INF-H7` (nested `.env`), `INF-M24` (same as `INF-C3`) |
| **False positive** |                                  1 | `ML-H3` — `/model_artifacts` is persistent EFS, not ephemeral disk                                                 |
| **Obsolete**       |                                  2 | `ML-M9` (depends on retired local `docker compose cp` path), `ML-M16` (SageMaker path gated off)                   |
| **Blocked**        |                                  1 | `INF-H3` — no domain/ACM cert; code ships behind `enable_https`                                                    |
| **Valid**          | ~214 IDs / ~208 unique root causes | everything else                                                                                                    |
| **Duplicates**     |                                  — | `INF-H8` ≡ `ML-C3`; `FE-H15` shares the backend root cause with `BE-D3`                                            |

Triage evidence lives in this change's review subagent runs; no finding was closed without a
file:line citation.

---

## 4. Event model and operating loop

**Cost per PR:** 1 commit on `main` + 1 PR open + 1 merge commit = **3 events**. Bot-authored
commits do not count. A CI-fix commit is +1.

**Daily plan:** 3–5 PRs = **9–15 events**, well under 42. The binding constraint is implementation
and review time, not the graph cap.

**Loop per PR**

1. Branch from latest `main`: `fix|core|perf|security|chore/<cluster>`.
2. Implement + add the regression test.
3. Run the local gate: `ruff`, `pytest`, `tsc --noEmit`, `jest`, `cargo test` (when touched),
   `terraform fmt -check -recursive terraform/` (when touched).
4. Dispatch `code-reviewer` on the branch diff. **Fix every finding, amend to one commit, re-review
   until clean.**
5. Push, open PR with: finding IDs, root cause, acceptance test, risk/rollback, "Closes" list.
6. Wait for **all** CI checks green. Fix failures on the same branch (new commit if amend would
   require a force-push).
7. Hand to Ahmed to merge. Do not start a dependent PR until the parent is merged.

**If a PR is not merged the same day,** the next dependent PR waits; independent PRs continue.

---

## 5. Day-by-day ledger

**Calendar:** D1 = Tue 17 Nov · D14 = Fri 4 Dec · D15 = Mon 7 Dec · D16 = Tue 8 Dec ·
D17 = Wed 9 Dec (verification/overflow). Weekends are not planned.

| Day               | PR                             | Findings                                                                               | Acceptance (short)                                                                           | Events |
| ----------------- | ------------------------------ | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -----: |
| **D1** Tue 17     | `docs/remediation-plan`        | this file                                                                              | CI green; approved                                                                           |      3 |
| **D2** Wed 18     | `security/auth-hardening`      | BE-C2, BE-C3, BE-M13                                                                   | bcrypt off-loop; constant-time unknown email; 422 on long fields                             |      3 |
|                   | `security/rate-limit-identity` | BE-C1, BE-M8, BE-L20                                                                   | trusted forwarded IP; WS metered; batch cost counted                                         |      3 |
|                   | `fix/redis-hardening`          | BE-M14, BE-L16, BE-L17                                                                 | CA verified; pool closed on shutdown; dead helpers gone                                      |      3 |
| **D3** Thu 19     | `fix/migration-truth`          | BE-C4, BE-C6, BE-M15, BE-L19                                                           | advisory lock; `_FIX_SQL` gone; autogenerate diff empty; offline SQL works                   |      3 |
|                   | `fix/mcp-dispatch`             | BE-M9, BE-M10, BE-L21                                                                  | invalid JSON-RPC → `-32600`; tool failure `isError:true`; version validated                  |      3 |
|                   | `fix/refresh-lifecycle`        | BE-M12, BE-L22                                                                         | expired rows purged; deactivated user cannot refresh                                         |      3 |
| **D4** Fri 20     | `chore/mcp-dead-path`          | BE-L18, BE-L24                                                                         | dead `FastMCP` path resolved; schemas memoised                                               |      3 |
|                   | `fix/startup-db`               | BE-C5, BE-C7                                                                           | env-var-only boot works; stuck query → 503, not hang                                         |      3 |
|                   | `fix/edge-surfaces`            | BE-M11, BE-L23, BE-L25                                                                 | replay survives timeout; CIMD pinned-IP; composite index                                     |      3 |
|                   | `chore/dependency-drift`       | INF-M9, INF-M17, INF-M18                                                               | Python 3.13, Node 22, one requirement source                                                 |      3 |
| **D5** Mon 23     | `fix/currency`                 | BE-D2, BE-D11, BE-D12, BE-M27, BE-L38                                                  | GBp×0.01; FX fail-closed; current-rate valuation; cost basis column                          |      3 |
| **D6** Tue 24     | `fix/newest-n`                 | BE-D3, BE-D7                                                                           | OHLCV + agent history return newest N, ascending                                             |      3 |
|                   | `fix/performance-series`       | BE-D1, BE-D9, BE-D10, BE-M31, BE-M32, BE-D14                                           | no IndexError; pre-start seed; closest-prior price; live-quote gate; to_thread               |      3 |
| **D7** Wed 25     | `fix/jsonb-encoding`           | BE-D13                                                                                 | dicts to `::jsonb`; drift run no longer 500s                                                 |      3 |
|                   | `fix/bedrock`                  | BE-M18, BE-M19                                                                         | Nova `converse()`; retry on throttle/5xx only                                                |      3 |
|                   | `fix/yfinance`                 | BE-M20, BE-M21, BE-M33                                                                 | 4xx not retried; nested news parsed; per-ticker lock                                         |      3 |
|                   | `fix/frontend-fractions`       | FE-H6, FE-H7, FE-M39, FE-M40                                                           | TWR/benchmark ×100; `direction`; real gain keys; fixtures fixed                              |      3 |
| **D8** Thu 26     | `fix/receipts-ocr`             | BE-M22, BE-M23, BE-M24                                                                 | cash/change excluded; one parse pass; sha256 hash                                            |      3 |
|                   | `fix/agent-tools`              | BE-D8, BE-D15, BE-M25, BE-M26, BE-M28, BE-M29                                          | empty portfolio guard; true max weight; cached quotes; sector persisted; SPY; row cap        |      3 |
|                   | `fix/frontend-currency`        | FE-C4, FE-M41                                                                          | subscription carries currency; GBP conversion before display                                 |      3 |
|                   | `fix/frontend-polling`         | FE-M19, FE-M20, FE-M21, FE-M22, FE-M23, FE-M24, FE-M25, FE-M38                         | await refetch; bulk perf; focus gate; error UI; request sequence                             |      3 |
| **D9** Fri 27     | `fix/drift-service`            | BE-D6, BE-M16, BE-M17, BE-M36                                                          | user-scoped tickers; batch insert; outlier bins; one PSI threshold                           |      3 |
|                   | `fix/receipts-endpoint`        | BE-D4, BE-D5, BE-M35                                                                   | chunked size guard; static health; UUID type                                                 |      3 |
|                   | `fix/frontend-session`         | FE-H5, FE-H14, FE-M26, FE-M27, FE-M31                                                  | offline launch keeps session; refresh epoch; GraphQL 401 retry; WS dispose; timeouts         |      3 |
|                   | `chore/frontend-dead-code`     | FE-M45, FE-M46, FE-M47, FE-L48                                                         | dead OCR module/deps gone; jest-native removed; exports pruned                               |      3 |
| **D10** Mon 30    | `fix/agent-exposure`           | BE-M30, BE-M34                                                                         | chat max length; limiter on 7 routes                                                         |      3 |
|                   | `chore/backend-cleanup`        | BE-L37, BE-L39, BE-L40, BE-L41, BE-L42, BE-L43, BE-L44, BE-L45, BE-L46, BE-L47, BE-L48 | holdings dedupe; dead schemas deleted; numeric bounds; no startup DDL                        |      3 |
|                   | `security/frontend-device`     | FE-H11, FE-H12, FE-H13, FE-M32, FE-M33, FE-M43                                         | cold-start lock; expo-crypto RNG; password removed; enrollment; key race; keychain level     |      3 |
|                   | `chore/frontend-polish`        | FE-C3, FE-H16, FE-H18, FE-M42, FE-L56                                                  | ticker/quote guard; shared chart scale; root expo start; no £0 confirm; clamp dates          |      3 |
| **D11** Tue 1 Dec | `fix/airflow3-migration`       | ML-M14, ML-M15, ML-L25, ML-L26                                                         | `dag_processor` keys; SDK imports; one pinned source                                         |      3 |
|                   | `fix/drift-dag`                | ML-C1, ML-H1, ML-L28, ML-L29                                                           | `src.drift`; pool init; branch wiring; model_version filter                                  |      3 |
|                   | `fix/frontend-receipts`        | FE-C2, FE-H8, FE-M34, FE-M35, FE-M36                                                   | update draft not create; paginate; real key; event + copy                                    |      3 |
|                   | `fix/frontend-conversations`   | FE-M28, FE-M29, FE-M30                                                                 | best-effort deposit; mapped history; stream guard                                            |      3 |
| **D12** Wed 2 Dec | `fix/ml-ingest`                | ML-C2, ML-M11, ML-M12                                                                  | `ALL` expands; upsert updates restated bars; failure ratio exits 1                           |      3 |
|                   | `fix/image-runtime`            | ML-C3, ML-H5, INF-H8, INF-H9, INF-M8, INF-M10, INF-M12, INF-M13, INF-M14, INF-M20      | one Python 3.13; GPU torch in venv; pinned uv; non-root; Airflow 3 default; immutable tags   |      3 |
|                   | `fix/frontend-projections`     | FE-H9, FE-H10, FE-H15, FE-H17, FE-M37, FE-L54, FE-L55                                  | real history span; period CAGR; cached fetches; zero guard; immutable state                  |      3 |
|                   | `fix/frontend-types`           | FE-L52, FE-L53                                                                         | typed navigation; source/time rendered                                                       |      3 |
| **D13** Thu 3 Dec | `fix/ml-promotion`             | ML-H2, ML-H4, ML-M6, ML-M8, ML-L20                                                     | run-id metrics; returned version; two-proportion test; atomic publish                        |      3 |
|                   | `perf/ml-memory`               | ML-M3, ML-M4, ML-M5, ML-M10                                                            | digest subsample; last-row refs; one weight pass; columnar fetch                             |      3 |
|                   | `fix/deploy-env`               | INF-H1, INF-M19                                                                        | env from ref; per-env state key; no auto tfvars                                              |      3 |
|                   | `fix/frontend-responsive`      | FE-L49, FE-L50, FE-L51, FE-M44, FE-L57                                                 | dimension hook; hoisted animated components; layout state; gesture root                      |      3 |
| **D14** Fri 4 Dec | `fix/ml-reference`             | ML-M13                                                                                 | jsonb codec/loads                                                                            |      3 |
|                   | `fix/ml-hpo`                   | ML-M1, ML-M2                                                                           | build once; fixed-population metric                                                          |      3 |
|                   | `chore/ml-dag-hygiene`         | ML-H6, ML-L27                                                                          | `default_var`; meaningful champion branch                                                    |      3 |
|                   | `fix/ml-baseline`              | ML-M7                                                                                  | chronological early stopping                                                                 |      3 |
|                   | `security/iam`                 | INF-H2, INF-M6, INF-M7                                                                 | OIDC sub restricted; SageMakerFullAccess gone; `RunTask` scoped                              |      3 |
| **D15** Mon 7 Dec | `chore/ml-low-batch`           | ML-L17, ML-L18, ML-L19, ML-L21, ML-L22, ML-L23, ML-L24, ML-L30, ML-L31, ML-L32         | labels logged; temp dirs; docstrings; seeded eval                                            |      3 |
|                   | `security/secrets`             | INF-H4, INF-H5, INF-M15                                                                | `valueFrom` secrets; JWT out of model; PEM provisioned                                       |      3 |
|                   | `fix/data-retention`           | INF-M1, INF-M2, INF-M3, INF-M26                                                        | 6y receipts; Redis HA/8.x; 7d backups + PI; state PAB                                        |      3 |
|                   | `fix/network-waf`              | INF-H6, INF-M4, INF-M25 (+ INF-H3 gated)                                               | NFS rule; CommonRuleSet; private prod path; gated HTTPS                                      |      3 |
| **D16** Tue 8 Dec | `chore/ci-supply-chain`        | INF-M16, INF-M21, INF-M23                                                              | Trivy IaC; audit gate; recursive fmt                                                         |      3 |
|                   | `fix/infra-hygiene`            | INF-C2, INF-H10, INF-M11, INF-M27                                                      | Airflow schema isolated; `desired_count` ignored; XCom pickling off; budget alarm fails plan |      3 |
|                   | `fix/sagemaker-gate`           | INF-M5                                                                                 | module defaults off; isolation contradiction removed                                         |      3 |
|                   | `chore/infra-cleanup`          | INF-M22 + all 12 LOW bullets (§6)                                                      | Makefile paths; dead locals/locks/outputs; CI timeouts                                       |      3 |
| **D17** Wed 9 Dec | **verification**               | —                                                                                      | full suites, gitleaks, terraform validate, status closeout                                   |      0 |

**Totals:** 55 PRs · **165 planned events** · peak day **15 events** · 42/day ceiling never
approached. D15–D17 are the approved buffer; if the schedule holds, D17 is verification only.

---

## 6. Risk and change control

| Risk                                         | Control                                                                                              |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Currency/perf changes alter persisted values | Migration or recompute script in the same PR; before/after fixture; rollback note                    |
| A PR's review finds unrelated bugs           | Fix regressions in-PR; log the rest in `docs/FIX-DISCOVERIES.md`; do not expand scope                |
| CI is red after opening                      | Fix on the same branch; +1 event; do not open a second PR for the same intent                        |
| A dependency PR lands mid-stream             | Rebase the branch; re-run local gate; CI is the authority                                            |
| A finding is larger than its slot            | Stop, move it to D17, re-plan the remaining days; never carry two unfinished PRs                     |
| New findings exceed 5/day                    | Freeze new branches, update this plan, re-baseline                                                   |
| `INF-H3` remains open                        | Accepted: no domain. The code path is gated and documented; revisit when a domain exists             |
| SageMaker/local model path re-enabled later  | `ML-M9`/`ML-M16` are obsolete only while the path is gated; reopen from the review doc if it returns |

---

## 7. Approval

**Approved 2026-11-16.** Execution order:

1. This file opens as `docs/remediation-plan` (D1) and waits for CI green.
2. Ahmed merges it.
3. D2 starts the next working day, in the order above.

No code branch exists until this file is merged.

## 8. Execution update (2026-11-22)

The 55-PR ledger above was superseded by area batches. All CRITICAL findings are closed. Batches landed: auth/session, migration truth, currency, performance series, MCP/GraphQL, receipts/OCR, agent tools, frontend money/session, frontend device security, frontend polling/projections/cleanup, ML image/promotion/runtime, and infra secrets/IAM/retention.

Still open: ML-H4 ensemble registration, ML-M8 atomic publish, HPO/memory items, INF-H1 (needs a state migration), INF-M15/M25, BE-L23 (CIMD rebinding), BE-M8 per-socket cap, BE-M23 OCR passes, BE-L37/L39, FE-L49/L52.

Working rule from 2026-11-21: floor of 40 GitHub contributions per day, then stop at the merged PR that crosses it. PRs are area batches with atomic commits.
