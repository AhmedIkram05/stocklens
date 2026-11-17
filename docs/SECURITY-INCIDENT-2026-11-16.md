# Security incident — committed credentials

**Date:** 2026-11-16
**Trigger:** full code review, finding `INF-C1` / `INF-C3` / `FE-C1`
**Status:** repository containment **done** · rotation **done (owner, 2026-11-16)** · history purge **optional — recommended skip**

This document contains **no secret values**. It lists where each value was exposed and
the exact steps to revoke, rotate and purge it.

---

## 1. Exposure inventory

| Artifact                                    | Status                                     | What it exposed                                                                                                                                                         | Introduced             |
| ------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| `terraform/tfplan`                          | **tracked until this change**              | A zip containing `tfstate` + `tfstate-prev`. State holds the RDS master password, JWT signing secret, Redis AUTH token, LangSmith API key, and the full `DATABASE_URL`. | `e71fc86` (2026-07-12) |
| `app.json` → `expo.extra.OCR_SPACE_API_KEY` | **removed in this change**                 | A live OCR.space key, serialised into every Expo build and readable from the shipped bundle.                                                                            | current tree           |
| `.env` (repo root)                          | deleted in `f04ea30`, **still in history** | Firebase/Google API key, Alpha Vantage key, OCR.space key (`EXPO_PUBLIC_*`).                                                                                            | `8296c35`              |
| `terraform/secrets.tf`                      | in history only                            | Resource definitions only (`random_password` references) — no literal values. No action.                                                                                | `14fd5d3`              |

The repository is public (`github.com/AhmedIkram05/stocklens`). Anyone who has cloned,
forked, or scraped it has these values. **Purging history does not un-leak them.** Rotation
is the only real remediation.

`backend/.env` exists locally but is gitignored and untracked; it is not part of this
incident.

---

## 2. Containment applied in this change

- Deleted `terraform/tfplan` from the working tree (it was tracked).
- Removed the entire `expo.extra` block from `app.json`; no source file reads
  `OCR_SPACE_API_KEY` any more (`ocrService.ts` is dead — only its test imports it).
- `.gitignore`: added `tfplan`, `tfplan.*`, `*.plan` (the old `*.tfplan` pattern did not
  match the extensionless default output).
- `.dockerignore`: `.env` patterns are now recursive (`**/.env`, `**/.env.*`), so
  `backend/.env` can no longer be baked into the root-context Airflow image; state/plan
  files are excluded too.
- `.gitleaks.toml`: removed the `paths = [".env"]` allowlist that suppressed every future
  `.env` finding. Only the historical commit is allowlisted until the purge.
- CI already runs `gitleaks/gitleaks-action@v3` (`.github/workflows/ci.yml:328`).

Verify locally:

```bash
git status --short                       # tfplan shows as D, config files as M
git ls-files | grep -E 'tfplan|(^|/)\.env$'   # must be empty
grep -r 'OCR_SPACE_API_KEY' app.json frontend/src   # only the dead test may match
```

---

## 3. Rotation — completed 2026-11-16

All items below were rotated by the owner on 2026-11-16. The commands remain as the
runbook for the next time a value is exposed.

**Verification note:** account `327936092014` / `eu-west-2` contains **no** `stocklens-*`
secrets, so the leaked `tfstate` refers to a dev stack that is no longer present (or to a
stack in another account/region). If any `stocklens-{db-password,jwt-secret,redis-pass,
langsmith-api-key}-*` secret still exists outside the configured account, rotate it there
too — the value in history is burned regardless.

Exact secret names for the `dev` environment (from `terraform/modules/secrets/main.tf`):

- `stocklens-dev-db-password`
- `stocklens-dev-jwt-secret`
- `stocklens-dev-redis-pass`
- `stocklens-dev-langsmith-api-key`
- `stocklens-dev-database-url` (older layout; update it if it still exists in state)

> **Terraform caveat.** These values are managed by `random_password` resources. Rotating
> them by hand in the console makes Terraform state stale, and the next `apply` may write
> the old value back. Prefer `terraform apply -replace=...` for managed secrets; use the
> console only where noted. `apply_immediately` is required for RDS.

### 3.1 RDS master password

```bash
# Prefer Terraform so state stays consistent:
terraform -chdir=terraform apply \
  -replace='module.database.random_password.db' -var-file=dev.tfvars

# Or rotate in place, then reconcile state:
aws rds modify-db-instance --db-instance-identifier stocklens-dev \
  --master-user-password '<new-password>' --apply-immediately
aws secretsmanager put-secret-value --secret-id stocklens-dev-db-password \
  --secret-string '<new-password>'
```

Then update the composed URL (if that secret exists):

```bash
aws secretsmanager put-secret-value --secret-id stocklens-dev-database-url \
  --secret-string 'postgresql://stocklens:<new-password>@<host>:5432/stocklens'
```

### 3.2 JWT signing secret

Rotating invalidates every issued access/refresh token (users are logged out).

```bash
openssl rand -base64 48          # generate
aws secretsmanager put-secret-value --secret-id stocklens-dev-jwt-secret \
  --secret-string '<new-secret>'
```

If Terraform owns it, `-replace='module.secrets.random_password.jwt'` instead, then restart
the ECS service so tasks pick up the new value:

```bash
aws ecs update-service --cluster stocklens-dev --service stocklens-dev \
  --force-new-deployment
```

### 3.3 Redis AUTH token

ElastiCache requires the `ROTATE` strategy when changing an auth token.

```bash
aws elasticache modify-replication-group \
  --replication-group-id stocklens-dev \
  --auth-token '<new-token>' --auth-token-update-strategy ROTATE \
  --apply-immediately

aws secretsmanager put-secret-value --secret-id stocklens-dev-redis-pass \
  --secret-string '<new-token>'
```

### 3.4 LangSmith API key

Revoke in LangSmith → Settings → API keys, create a replacement, then:

```bash
aws secretsmanager put-secret-value --secret-id stocklens-dev-langsmith-api-key \
  --secret-string '<new-key>'
```

### 3.5 OCR.space key

Revoke and regenerate at <https://ocr.space/ocrapi>. The application path is backend-only
(`POST /receipts/scan`); **do not** put the replacement in `app.json` or any `EXPO_PUBLIC_*`
variable. If a client-side fallback is ever needed, proxy it through the backend.

### 3.6 Alpha Vantage key

Regenerate at <https://www.alphavantage.co/support/#api-key>. Not used by the current code
path (quotes go through yfinance), but the old value is in history and must be treated as
burned.

### 3.7 Google / Firebase API key

In Google Cloud Console → APIs & Services → Credentials:

1. Restrict the key to the intended APIs, Android/iOS bundle IDs, and HTTP referrers.
2. Rotate it. A Firebase **web** API key is an identifier rather than a true secret, but an
   unrestricted `AIza…` key can be abused against billable APIs; treat this one as leaked.

---

## 4. Optional — purge history (only after rotation)

**Rotation is the fix. History purging is hygiene.** Once every value in §3 is revoked, the
old commits contain dead strings. Purging is still worth doing before the repo is shared
widely, but it is not what makes you safe.

### Does this affect the contributions graph?

**No, if done correctly.** GitHub attributes contributions by author email + author date,
and `git filter-repo` preserves author name, author email and both dates on every rewritten
commit. It only changes commit SHAs (because parent hashes change).

Rules to keep it that way:

- Do **not** pass `--mailmap`, `--replace-text`, `--email-callback`, or
  `--preserve-commit-hashes`-style options. Plain `--invert-paths` is enough.
- Work in a fresh **mirror clone**, never the working repo.
- Before pushing, compare both trees:
  ```bash
  # old
  git -C /path/to/old log --all --format='%ae %ad' --date=short | sort | uniq -c > /tmp/before
  # rewritten mirror
  git -C /tmp/stocklens-mirror.git log --all --format='%ae %ad' --date=short | sort | uniq -c > /tmp/after
  diff /tmp/before /tmp/after        # must be identical
  git -C /tmp/stocklens-mirror.git rev-list --count --all   # must equal the old count
  ```
  Your history has 1,359 commits on `main`; the count must not change. The only difference
  should be SHAs.
- Keep the old remote/branch reachable until the new one is verified.

**Blast radius if you skip it:** none to the graph, none to open PRs. **If you do it:**
1,359 commits get new SHAs, every open PR needs a rebase, every fork keeps the old history
(rotation is what neutralises that), and any SHA referenced in an issue or doc becomes
unreachable.

`git-filter-repo` and `gitleaks` are installed locally. **This session's git guard blocks
history rewrites and force-pushes**, so run this yourself. Use a fresh mirror clone — running
it in the working repo will fail its safety check.

```bash
git clone --mirror https://github.com/AhmedIkram05/stocklens.git /tmp/stocklens-mirror.git
cd /tmp/stocklens-mirror.git

git filter-repo --invert-paths \
  --path terraform/tfplan \
  --path .env

git push --force --all
git push --force --tags
```

Then re-clone your working copy (do not pull into the rewritten one):

```bash
git clone https://github.com/AhmedIkram05/stocklens.git ~/stocklens-clean
```

Finish:

1. Delete the `commits` allowlist from `.gitleaks.toml` (the commit no longer exists).
2. Run `gitleaks git --redact --config .gitleaks.toml` and confirm zero findings.
3. Ask any open PR authors to rebase onto the rewritten `main`; old PRs will show unrelated
   diffs and cannot be merged cleanly.
4. Forks and cached GitHub views keep the old objects. Rotation already neutralises them; if
   you want the objects removed from GitHub itself, open a support request asking for a
   cache purge after the force-push.

> If `filter-repo` refuses because the mirror is not considered fresh, add `--force`. Never
> run `git filter-repo` in the working repo while it has uncommitted changes.

---

## 5. Verification

```bash
# 1. No leaked artifacts anywhere in history
git log --all --oneline -- terraform/tfplan .env      # empty after purge
git rev-list --all --objects | grep -E 'tfplan|(^|/)\.env$'  # empty

# 2. Secret scan is clean
#    Note: gitleaks cannot inspect inside the tfplan zip, and the historical
#    .env commit is allowlisted until/unless history is rewritten.
gitleaks git --redact --config .gitleaks.toml

# 3. Current tree has no provider keys
git ls-files | grep -E 'tfplan|(^|/)\.env$'           # empty
grep -rn 'OCR_SPACE_API_KEY' app.json frontend/src    # only the dead test

# 4. The Airflow image no longer contains the nested env file
docker build -f airflow/Dockerfile -t stocklens-airflow:check .
docker run --rm stocklens-airflow:check test ! -f /app/backend/.env

# 5. Old credentials are dead
#    - app login works with the new JWT secret (old tokens 401)
#    - backend connects to RDS with the new password
#    - Celery/Redis/agent paths reconnect with the new AUTH token
```

---

## 6. Prevention

1. **GitHub → Settings → Code security:** enable _Secret scanning_ and _Push protection_ for
   the repository (free for public repos). This is the only control that stops a secret
   before it lands.
2. Keep `gitleaks/gitleaks-action@v3` in CI (already present). Never widen the allowlist to a
   path — allowlist a specific historical commit only, and delete it after purge.
3. Never write plan/state files inside the repository: use
   `terraform plan -out=/tmp/tfplan` or `$TMPDIR/tfplan`.
4. `git add -A` is how `tfplan` got in. Review `git status` and `git diff --cached --stat`
   before committing; pre-commit already runs `detect-private-key`.
5. Keep `backend/.env` local-only, and remember `.dockerignore` patterns must be recursive for
   nested build contexts.

---

## 7. Checklist

- [x] Remove `terraform/tfplan` from the tree
- [x] Remove the OCR key from `app.json`
- [x] Close the `.gitignore` / `.dockerignore` gaps
- [x] Tighten the gitleaks allowlist
- [x] Rotate RDS password + `DATABASE_URL` _(owner, 2026-11-16)_
- [x] Rotate JWT signing secret _(owner, 2026-11-16)_
- [x] Rotate Redis AUTH token _(owner, 2026-11-16)_
- [x] Rotate LangSmith key _(owner, 2026-11-16)_
- [x] Revoke/regenerate OCR.space key _(owner, 2026-11-16)_
- [x] Regenerate Alpha Vantage key _(owner, 2026-11-16)_
- [x] Restrict/rotate the Google/Firebase key _(owner, 2026-11-16)_
- [ ] _(optional)_ Purge `terraform/tfplan` and `.env` from history
- [ ] _(optional)_ Force-push and re-clone working copies
- [ ] _(optional)_ Delete the gitleaks commit allowlist
- [ ] Enable GitHub secret-scanning push protection
- [ ] Verify with the commands in §5

---

## 8. Closeout

- **Rotation:** completed by the owner on 2026-11-16. The leaked values are revoked.
- **AWS metadata check:** no `stocklens-*` secrets exist in account `327936092014` /
  `eu-west-2`; the state file references a torn-down dev stack.
- **Scanner:** `gitleaks git --redact` reports no leaks. It cannot inspect inside the
  `tfplan` zip, and the historical `.env` commit remains allowlisted.
- **Working tree:** `terraform/tfplan` deleted; OCR key removed; ignore and Docker-context
  gaps closed.
- **History purge: deliberately skipped.** Rotation neutralises the old values. A rewrite
  would change 1,359 SHAs, break every open PR, and force every clone/fork to be recreated,
  with no security gain. The runbook in §4 stays for a future incident where a value cannot
  be rotated.
- **Residual risk:** the revoked strings remain readable in public history and in forks.
  They cannot be used. Enable GitHub secret-scanning push protection so the next one never
  lands.
