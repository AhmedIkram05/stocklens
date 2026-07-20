# ADR 006: Champion Model Delivery — S3 Bootstrap over MLflow-Runtime Load

**Date:** 2026-07-08
**Status:** Accepted
**Phase:** 5 — Production Deployment

## Context

The Phase 5 brief states "/predict loads the champion LSTM from MLflow". The serving path today (`backend/src/prediction/service.py`) loads a local `.pt` from `PREDICTION_MODEL_PATH=/model_artifacts/champion/model.pt`. MLflow is used **only at train time** (`backend/ml/mlflow_manager.py` calls `save_champion_to_disk()` which writes `model.pt` + vocab + means/stds to a local directory). There is **no `import mlflow` anywhere in `backend/src/`**, and the Fargate image only `mkdir -p /model_artifacts/champion` (empty dir).

Two real options exist for getting the champion into the stateless Fargate task:

1. **Load from MLflow at runtime** — add `mlflow.pytorch.load_model()` to the serving container, pin MLflow as a runtime dependency, and fetch the `champion` registry alias on each task start.
2. **S3 bootstrap** — training / Airflow publishes the champion `.pt` (+ vocab + means/stds) to the existing `mlflow-artifacts` S3 bucket; a thin entrypoint bootstrap in the Fargate task downloads it to `/model_artifacts/champion/` before `prediction_service.load_model` runs. `load_model` is unchanged.

## Decision

Adopt **S3 bootstrap**. The serving container downloads the champion artifact from S3 at task startup via a small bootstrap script invoked by the container entrypoint, then `prediction_service.load_model` loads the local `.pt` exactly as it does today. MLflow stays a **train-time-only** concern.

## Rationale

- The serving container is built to be lean (3-stage Dockerfile, `uvicorn --workers 2`). Pulling MLflow + its transitive deps (gunicorn/werkzeug/etc.) into the runtime image contradicts that design and bloats a Cold Start / deploy.
- MLflow's registry `champion` alias is already materialised to disk by `save_champion_to_disk` at train time. Prom extending that one function to also push to S3 is a few lines and keeps the "champion" notion single-sourced.
- S3 delivery is the same mechanism already used for drift reports (`backend/src/drift/utils.py` uses boto3 S3), so it reuses an established, IAM-scoped pattern rather than inventing a new runtime MLflow client.
- The `.pt` is ~0.5 MB; download at startup is sub-second and only happens on task (re)start, not per request. The 6h Redis result cache already absorbs per-ticker request load.

## Consequences

- `save_champion_to_disk()` (train side) and/or the Airflow retraining DAG must also `put_object` the champion bundle to `s3://<mlflow-artifacts>/champion/`.
- The Fargate task gains an entrypoint bootstrap (shell or small Python) that `aws s3 cp`s `s3://<mlflow-artifacts>/champion/` → `/model_artifacts/champion/` before launching uvicorn.
- The task role (already least-priv in `terraform/iam.tf`) needs a scoped `s3:GetObject` on the champion prefix.
- `prediction_service.load_model` is unchanged — zero serving-code churn.
- If the S3 fetch fails, the task must fail fast (non-zero exit) so ECS does not serve a task with no model; document this in the bootstrap.

## Alternatives Considered

| Alternative                    | Reason Rejected                                                                                  |
| ------------------------------ | ------------------------------------------------------------------------------------------------ |
| MLflow `load_model` at runtime | Heavy runtime dep in lean image; MLflow client resilience on Cold Start; no code path yet exists |
| Bake `.pt` into the image      | Champ changes weekly → rebuild + redeploy image on every promotion; defeats ECR immutable tags   |
| EFS mount for model artifacts  | Extra recurring cost + mount plumbing for a 0.5 MB file; overkill vs one-shot S3 download        |
