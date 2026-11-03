"""Logic tests for the weekly retraining DAG handlers.

``test_dag.py`` validates DAG structure and the DSN helpers; this module
exercises each handler's branching with its heavy collaborators (asyncpg
connection, drift detector, DB session) stubbed — including a failure path per
handler, so a silent MLOps failure cannot ship unnoticed.

Runs in CI's dedicated Airflow job: apache-airflow is not in the backend venv,
and the CI airflow job installs only ``airflow/requirements.txt`` (which carries
no ``asyncpg``), so the asyncpg module is injected as a fake rather than assumed.
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest

from dags import weekly_retraining


# ── fakes ──────────────────────────────────────────────────────────────────
class _FakeAsyncConn:
    """Stands in for an asyncpg connection across the DB-backed handlers."""

    def __init__(self, *, row=None, rows=None, execute_result="DELETE 0"):
        self.row = row
        self.rows = rows if rows is not None else []
        self.execute_result = execute_result
        self.executed: list[str] = []
        self.closed = False

    async def fetchrow(self, *_args, **_kwargs):
        return self.row

    async def fetch(self, _query, *_args, **_kwargs):
        return self.rows

    async def execute(self, query, *_args, **_kwargs):
        self.executed.append(query)
        return self.execute_result

    async def close(self):
        self.closed = True


class _StubPgConn:
    login = "stocklens"
    password = "pw"
    host = "db"
    port = 5432
    schema = "stocklens"


class _Completed:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def _install_asyncpg(monkeypatch, connect):
    module = types.ModuleType("asyncpg")
    setattr(module, "connect", connect)
    monkeypatch.setitem(sys.modules, "asyncpg", module)
    return module


@pytest.fixture
def stub_dsn(monkeypatch):
    """Skip the Airflow connection store — handlers only need a DSN string."""
    monkeypatch.setattr(weekly_retraining, "_pg_dsn", lambda: "postgresql://stub/db")


@pytest.fixture
def fake_asyncpg(monkeypatch):
    """Install a fake asyncpg whose connect() returns the supplied connection."""

    def install(conn):
        async def connect(_dsn):
            return conn

        _install_asyncpg(monkeypatch, connect)
        return conn

    return install


# ── _check_new_ohlcv_data ──────────────────────────────────────────────────
class TestCheckNewOhlcvData:
    def test_no_max_date_skips(self, stub_dsn, fake_asyncpg):
        conn = fake_asyncpg(_FakeAsyncConn(row={"max_date": None, "champion_trained_at": None}))
        assert weekly_retraining._check_new_ohlcv_data() == "skip_retraining"
        assert conn.closed

    def test_no_champion_bootstraps_training(self, stub_dsn, fake_asyncpg):
        fake_asyncpg(_FakeAsyncConn(row={"max_date": date(2026, 7, 1), "champion_trained_at": None}))
        assert weekly_retraining._check_new_ohlcv_data() == "train_challenger"

    def test_advance_at_threshold_trains(self, stub_dsn, fake_asyncpg):
        trained = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_asyncpg(
            _FakeAsyncConn(
                row={
                    "max_date": (trained + timedelta(days=14)).date(),
                    "champion_trained_at": trained,
                }
            )
        )
        assert weekly_retraining._check_new_ohlcv_data() == "train_challenger"

    def test_advance_below_threshold_skips(self, stub_dsn, fake_asyncpg):
        trained = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_asyncpg(
            _FakeAsyncConn(
                row={
                    "max_date": (trained + timedelta(days=3)).date(),
                    "champion_trained_at": trained,
                }
            )
        )
        assert weekly_retraining._check_new_ohlcv_data() == "skip_retraining"

    def test_connect_failure_propagates(self, stub_dsn, monkeypatch):
        async def connect(_dsn):
            raise ConnectionError("db down")

        _install_asyncpg(monkeypatch, connect)
        with pytest.raises(ConnectionError, match="db down"):
            weekly_retraining._check_new_ohlcv_data()


# ── _detect_new_champion ───────────────────────────────────────────────────
class TestDetectNewChampion:
    def test_recent_champion_triggers_capture(self, stub_dsn, fake_asyncpg):
        trained = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        fake_asyncpg(_FakeAsyncConn(row={"trained_at": trained}))
        assert weekly_retraining._detect_new_champion() == "capture_reference_distributions"

    def test_old_champion_skips_capture(self, stub_dsn, fake_asyncpg):
        trained = datetime.now(tz=timezone.utc) - timedelta(hours=10)
        fake_asyncpg(_FakeAsyncConn(row={"trained_at": trained}))
        assert weekly_retraining._detect_new_champion() == "skip_reference_capture"

    def test_no_champion_skips_capture(self, stub_dsn, fake_asyncpg):
        fake_asyncpg(_FakeAsyncConn(row=None))
        assert weekly_retraining._detect_new_champion() == "skip_reference_capture"

    def test_connect_failure_propagates(self, stub_dsn, monkeypatch):
        async def connect(_dsn):
            raise RuntimeError("registry unreachable")

        _install_asyncpg(monkeypatch, connect)
        with pytest.raises(RuntimeError, match="registry unreachable"):
            weekly_retraining._detect_new_champion()


# ── _cleanup ───────────────────────────────────────────────────────────────
class TestCleanup:
    def test_prunes_both_tables_and_closes(self, stub_dsn, fake_asyncpg):
        conn = fake_asyncpg(_FakeAsyncConn(execute_result="DELETE 5"))
        weekly_retraining._cleanup()
        assert len(conn.executed) == 2
        assert conn.closed

    def test_delete_failure_propagates(self, stub_dsn, fake_asyncpg):
        class _BoomConn(_FakeAsyncConn):
            async def execute(self, *_args, **_kwargs):
                raise RuntimeError("delete failed")

        fake_asyncpg(_BoomConn())
        with pytest.raises(RuntimeError, match="delete failed"):
            weekly_retraining._cleanup()


# ── _run_ingest / _seed_script_path ────────────────────────────────────────
class TestRunIngest:
    def test_success_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(weekly_retraining, "_seed_script_path", lambda: "/tmp/seed.py")
        monkeypatch.setattr(weekly_retraining, "_pg_conn", _StubPgConn)
        monkeypatch.setattr(weekly_retraining.subprocess, "run", lambda *_a, **_k: _Completed(0))
        weekly_retraining._run_ingest()

    def test_nonzero_exit_raises(self, monkeypatch):
        monkeypatch.setattr(weekly_retraining, "_seed_script_path", lambda: "/tmp/seed.py")
        monkeypatch.setattr(weekly_retraining, "_pg_conn", _StubPgConn)
        monkeypatch.setattr(weekly_retraining.subprocess, "run", lambda *_a, **_k: _Completed(1))
        with pytest.raises(RuntimeError, match="OHLCV ingest failed"):
            weekly_retraining._run_ingest()


def test_seed_script_path_missing_raises(monkeypatch):
    monkeypatch.setattr(weekly_retraining.os.path, "exists", lambda _path: False)
    with pytest.raises(FileNotFoundError):
        weekly_retraining._seed_script_path()


# ── _run_drift_detection ───────────────────────────────────────────────────
def _register_fake_module(monkeypatch, name, **attrs):
    """Inject a fake module (and any missing parent packages) into sys.modules."""
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            package = types.ModuleType(parent)
            package.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, parent, package)
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def drift_stack(monkeypatch):
    """Install fake drift/DB collaborators and expose their recorded calls."""
    state = types.SimpleNamespace(
        champion={"model_version": "v2", "metrics": {"reference_distributions": {"f": [1, 2]}}},
        holdings=[{"ticker": "AAPL"}],
        logs=[
            {
                "ticker": "AAPL",
                "prediction": 1,
                "features": {},
                "feature_stats": {},
                "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            }
        ],
        metric_calls=[],
        upload_calls=[],
        compute_calls=[],
        compute_error=None,
    )

    class _Conn:
        async def fetchrow(self, *_a, **_k):
            return state.champion

        async def fetch(self, query, *_a, **_k):
            if "FROM holdings" in query:
                return state.holdings
            if "FROM prediction_log" in query:
                return state.logs
            return []

    class _Ctx:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_exc):
            return False

    class _Detector:
        async def compute_drift(self, **kwargs):
            state.compute_calls.append(kwargs)
            if state.compute_error is not None:
                raise state.compute_error
            return {
                "metrics": [{"ticker": "AAPL", "psi": 0.2}],
                "alerts_triggered": 1,
                "max_psi": 0.2,
                "max_js_divergence": 0.1,
            }

    class _Reporter:
        def generate_drift_report(self, _ref_df, _cur_df):
            return "/tmp/report.html", "rid-1"

    async def _create_drift_metric(**_kwargs):
        state.metric_calls.append(_kwargs)

    def _upload(path, key):
        state.upload_calls.append((path, key))

    _register_fake_module(monkeypatch, "drift.evidently_reporter", EvidentlyReporter=_Reporter)
    _register_fake_module(
        monkeypatch,
        "drift.repository",
        create_drift_metric=_create_drift_metric,
        generate_drift_run_id=lambda: "run-1",
    )
    _register_fake_module(
        monkeypatch,
        "drift.router",
        _build_current_dataframe=lambda _logs: object(),
        _build_reference_dataframe=lambda _ref: object(),
    )
    _register_fake_module(monkeypatch, "drift.service", DriftDetector=_Detector)
    _register_fake_module(
        monkeypatch,
        "drift.utils",
        build_s3_key=lambda rid, name: f"{rid}/{name}",
        upload_report_to_s3=_upload,
    )
    _register_fake_module(monkeypatch, "src.database.connection", connection_ctx=lambda: _Ctx())
    return state


class TestRunDriftDetection:
    def test_happy_path_persists_metrics_and_uploads(self, drift_stack):
        weekly_retraining._run_drift_detection()
        assert drift_stack.compute_calls
        assert len(drift_stack.metric_calls) == 1
        assert drift_stack.upload_calls == [("/tmp/report.html", "run-1/drift_report_rid-1.html")]

    def test_no_champion_skips(self, drift_stack):
        drift_stack.champion = None
        weekly_retraining._run_drift_detection()
        assert drift_stack.compute_calls == []
        assert drift_stack.upload_calls == []

    def test_missing_reference_dist_skips_report(self, drift_stack):
        drift_stack.champion = {"model_version": "v2", "metrics": {}}
        weekly_retraining._run_drift_detection()
        assert drift_stack.metric_calls  # metrics still persisted
        assert drift_stack.upload_calls == []

    def test_compute_error_propagates(self, drift_stack):
        drift_stack.compute_error = RuntimeError("drift blew up")
        with pytest.raises(RuntimeError, match="drift blew up"):
            weekly_retraining._run_drift_detection()
