"""
Validate the Airflow DAG structure.

Run with:
    python -m pytest airflow/dags/test_dag.py -v

Requires Airflow installed (pip install apache-airflow).
"""

from __future__ import annotations

from airflow.models import DagBag


def test_dag_imports() -> None:
    """Verify the DAG file imports without errors."""
    dagbag = DagBag(dag_folder="airflow/dags/", include_examples=False)
    assert len(dagbag.import_errors) == 0, f"DAG import errors: {dagbag.import_errors}"


def test_dag_structure() -> None:
    """Verify the weekly retraining DAG has expected tasks."""
    dagbag = DagBag(dag_folder="airflow/dags/", include_examples=False)
    dag = dagbag.get_dag("stocklens_weekly_retraining")
    assert dag is not None, "DAG 'stocklens_weekly_retraining' not found"
    assert len(dag.tasks) >= 6, f"Expected ≥6 tasks, got {len(dag.tasks)}"
    assert dag.schedule == "0 6 * * 1", f"Expected weekly schedule, got {dag.schedule}"


def test_dag_default_args() -> None:
    """Verify DAG has sensible default args."""
    dagbag = DagBag(dag_folder="airflow/dags/", include_examples=False)
    dag = dagbag.get_dag("stocklens_weekly_retraining")
    assert dag is not None
    assert dag.default_args.get("retries", 0) >= 1, "Expected ≥1 retry"
    timeout = dag.default_args.get("execution_timeout")
    assert timeout is not None and timeout.seconds >= 14400, "Expected ≥4h timeout"
