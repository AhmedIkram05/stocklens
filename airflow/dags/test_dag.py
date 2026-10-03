"""
Validate the Airflow DAG structure and its DB connection helpers.

Run with:
    python -m pytest airflow/dags/test_dag.py -v

Requires the Airflow extras (pip install -r airflow/requirements.txt); CI
runs this in a dedicated job because the backend venv does not carry them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from airflow.hooks.base import BaseHook
from airflow.models import DagBag

from dags import weekly_retraining

DAG_FOLDER = Path(__file__).parent
DAG_ID = "stocklens_weekly_retraining"


@pytest.fixture(scope="module")
def dag():
    """The parsed DAG, shared by the structural tests.

    Read off `DagBag.dags` rather than `get_dag()`: the latter queries the
    metadata database, which a bare parse has never initialised.
    """
    dagbag = DagBag(dag_folder=DAG_FOLDER)
    assert not dagbag.import_errors, f"DAG import errors: {dagbag.import_errors}"
    parsed = dagbag.dags.get(DAG_ID)
    assert parsed is not None, f"DAG '{DAG_ID}' not found in {sorted(dagbag.dags)}"
    return parsed


def test_dag_imports() -> None:
    """Verify the DAG file imports without errors."""
    dagbag = DagBag(dag_folder=DAG_FOLDER)
    assert len(dagbag.import_errors) == 0, f"DAG import errors: {dagbag.import_errors}"


def test_dag_structure(dag) -> None:
    """Verify the weekly retraining DAG has expected tasks."""
    assert len(dag.tasks) >= 6, f"Expected ≥6 tasks, got {len(dag.tasks)}"
    assert dag.schedule == "0 6 * * 1", f"Expected weekly schedule, got {dag.schedule}"


def test_dag_default_args(dag) -> None:
    """Verify DAG has sensible default args."""
    assert dag.default_args.get("retries", 0) >= 1, "Expected ≥1 retry"
    timeout = dag.default_args.get("execution_timeout")
    assert timeout is not None and timeout.seconds >= 14400, "Expected ≥4h timeout"


# ── postgres_default → asyncpg DSN ─────────────────────────────────────────────
# The DAG builds its DSN by hand instead of going through a provider hook, so
# the formatting is ours to get wrong. These pin it.


class _StubConnection:
    """Stands in for the object BaseHook.get_connection returns."""

    def __init__(self, **overrides):
        fields = {
            "login": "stocklens",
            "password": "s3cret",
            "host": "db",
            "port": 5432,
            "schema": "stocklens",
        }
        fields.update(overrides)
        for name, value in fields.items():
            setattr(self, name, value)


@pytest.fixture
def stub_hook(monkeypatch):
    """Patch BaseHook.get_connection so no Airflow connection store is needed."""

    def install(**overrides):
        conn = _StubConnection(**overrides)
        monkeypatch.setattr(BaseHook, "get_connection", lambda conn_id: conn)
        return conn

    return install


def test_pg_conn_reads_postgres_default(stub_hook) -> None:
    """_pg_conn resolves the stocklens connection from postgres_default."""
    conn = stub_hook()
    assert weekly_retraining._pg_conn() is conn


def test_pg_dsn_formats_all_connection_fields(stub_hook) -> None:
    """Every part of the connection lands in the DSN, not just host and port."""
    stub_hook(
        login="user", password="pw", host="postgres.internal", port=6543, schema="analytics"
    )
    assert weekly_retraining._pg_dsn() == "postgresql://user:pw@postgres.internal:6543/analytics"


def test_pg_dsn_defaults_schema_to_stocklens(stub_hook) -> None:
    """A connection with no schema falls back to the stocklens database.

    Airflow leaves `schema` empty when the connection was created from a URL
    without one, so the fallback is the common path, not an edge case.
    """
    stub_hook(schema=None)
    assert weekly_retraining._pg_dsn() == "postgresql://stocklens:s3cret@db:5432/stocklens"


def test_pg_dsn_is_url_safe_against_empty_password(stub_hook) -> None:
    """An empty password yields a valid DSN rather than a doubled colon."""
    stub_hook(password=None)
    assert weekly_retraining._pg_dsn() == "postgresql://stocklens:@db:5432/stocklens"
