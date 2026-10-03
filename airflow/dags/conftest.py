"""
Test-only Airflow configuration for the DAG suite.

`weekly_retraining.py` reads its ECS/logging wiring from Airflow Variables in
the module body, so parsing the DAG fails outright when the metadata store is
empty -- `Variable.get("ecs_cluster_name")` raises before any task exists. CI
parses with no Airflow deployment behind it, so the variables are supplied here
as `AIRFLOW_VAR_*` env vars, which `Variable.get` resolves before touching the
database.

Values are placeholders: nothing here is asserted against, it only has to be
parseable. Anything asserted lives in the tests.

Airflow picks this directory up as a DAG folder and finds no DAG here, so the
file is inert at runtime.
"""

from __future__ import annotations

import os

# Variables read in weekly_retraining's module body (the EcsRunTaskOperator
# wiring). `private_subnet_ids` is split on "," so it has to be a string.
PARSE_TIME_VARIABLES = {
    "app_name": "stocklens",
    "ecs_cluster_name": "test-cluster",
    "ml_training_task_definition": "stocklens-ml-training:42",
    "private_subnet_ids": "subnet-aaa,subnet-bbb",
    "airflow_sg_id": "sg-test",
    "aws_region": "eu-west-1",
    "environment": "test",
    "database_url": "postgresql://stocklens:stocklens@postgres:5432/stocklens",
    "mlflow_tracking_uri": "http://mlflow:5000",
    "champion_s3_uri": "s3://stocklens-test/champions/",
    "training_tickers": "ALL",
    "ml_ohlcv_years": "10",
    "ml_threshold_mult": "1.0",
    "ml_seeds": "42",
}

for _key, _value in PARSE_TIME_VARIABLES.items():
    os.environ.setdefault(f"AIRFLOW_VAR_{_key.upper()}", _value)
