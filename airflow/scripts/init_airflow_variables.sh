#!/bin/bash
# Init script for Airflow — seeds Airflow Variables from environment variables.
# Runs after `airflow db migrate` so the metadata DB is ready.
# This ensures Variable.get() works in DAGs without requiring the values
# to be manually set via the Airflow UI.
#
# For env-var-backed reads in Python code, see src.utils.get_airflow_var()
# which checks os.environ first (no init needed), falls back to Variable.get().

set -euo pipefail

echo "[init_airflow_variables] Starting..."

# Helper: set a variable only if not already set. Checks multiple env var names
# in order (e.g. AIRFLOW_VAR_X then X) for compatibility across ECS and local.
set_var_if() {
    local airflow_key="$1"
    shift
    local env_value=""

    for env_key in "$@"; do
        local val="${!env_key:-}"
        if [[ -n "$val" ]]; then
            env_value="$val"
            break
        fi
    done

    # Skip if already set (idempotent — don't overwrite user changes)
    if airflow variables get "$airflow_key" &>/dev/null; then
        echo "[init_airflow_variables] $airflow_key already set (skipping)"
        return
    fi

    if [[ -n "$env_value" ]]; then
        echo "[init_airflow_variables] Setting $airflow_key (from $env_key)"
        airflow variables set "$airflow_key" "$env_value"
    else
        echo "[init_airflow_variables] No env var found for $airflow_key — skipping"
    fi
}

# Set a variable to a literal default only if it is still unset (never
# overwrites: set_var_if runs first for env-backed values).
set_var_default() {
    local airflow_key="$1"
    local literal_value="$2"

    if airflow variables get "$airflow_key" &>/dev/null; then
        return
    fi
    echo "[init_airflow_variables] Setting $airflow_key (default: $literal_value)"
    airflow variables set "$airflow_key" "$literal_value"
}

# ── AWS / ECS ──────────────────────────────────────────────────────────
set_var_if "aws_region"           "AIRFLOW_VAR_AWS_REGION" "AWS_REGION"
set_var_if "ecs_cluster_name"     "AIRFLOW_VAR_ECS_CLUSTER_NAME" "ECS_CLUSTER_NAME"
set_var_if "ml_training_task_definition" "AIRFLOW_VAR_ML_TRAINING_TASK_DEFINITION" "ML_TRAINING_TASK_DEFINITION"
set_var_if "private_subnet_ids"    "AIRFLOW_VAR_PRIVATE_SUBNET_IDS" "PRIVATE_SUBNET_IDS"
set_var_if "airflow_sg_id"        "AIRFLOW_VAR_AIRFLOW_SG_ID" "AIRFLOW_SG_ID"

# ── Database ───────────────────────────────────────────────────────────
set_var_if "database_url"         "AIRFLOW_VAR_DATABASE_URL" "DATABASE_URL"

# ── MLflow ─────────────────────────────────────────────────────────────
set_var_if "mlflow_tracking_uri"  "AIRFLOW_VAR_MLFLOW_TRACKING_URI" "MLFLOW_TRACKING_URI"

# ── Champion ──────────────────────────────────────────────────────────
set_var_if "champion_s3_uri"     "AIRFLOW_VAR_CHAMPION_S3_URI" "CHAMPION_S3_URI"

# ── ML training recipe (must match the locally-validated rebuild) ─────
# Falls back to literal defaults when no env var is provided, so a bare
# local `docker compose up airflow` still gets the winning recipe.
set_var_if "training_tickers"    "AIRFLOW_VAR_TRAINING_TICKERS" "TRAINING_TICKERS"
set_var_if "ml_ohlcv_years"      "AIRFLOW_VAR_ML_OHLCV_YEARS" "ML_OHLCV_YEARS"
set_var_if "ml_threshold_mult"   "AIRFLOW_VAR_ML_THRESHOLD_MULT" "ML_THRESHOLD_MULT"
set_var_if "ml_seeds"            "AIRFLOW_VAR_ML_SEEDS" "ML_SEEDS"
set_var_default "training_tickers"  "ALL"   # full S&P 500 universe
set_var_default "ml_ohlcv_years"    "10"
set_var_default "ml_threshold_mult" "2.0"
set_var_default "ml_seeds"          "5"

# ── App ───────────────────────────────────────────────────────────────
set_var_if "app_name"             "AIRFLOW_VAR_APP_NAME" "APP_NAME"
set_var_if "environment"          "AIRFLOW_VAR_ENVIRONMENT" "ENVIRONMENT"

echo "[init_airflow_variables] Done."
