"""
Tests for MLflowManager.

All tests mock mlflow to avoid needing an MLflow server.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM


def _mock_mlflow() -> MagicMock:
    """Patch sys.modules so mlflow imports don't fail outside Docker."""
    mock = MagicMock()
    mock.set_tracking_uri = MagicMock()
    mock.set_experiment = MagicMock()
    mock.tracking = MagicMock()
    mock.tracking.MlflowClient = MagicMock()
    mock.active_run = MagicMock()
    mock.start_run = MagicMock()
    mock.end_run = MagicMock()
    mock.log_params = MagicMock()
    mock.log_metrics = MagicMock()
    mock.log_artifact = MagicMock()
    mock.log_input = MagicMock()
    mock.set_tag = MagicMock()
    mock.data = MagicMock()
    mock.data.from_numpy = MagicMock()
    mock.pytorch = MagicMock()
    mock.pytorch.autolog = MagicMock()
    mock.pytorch.log_model = MagicMock()
    mock.system_metrics = MagicMock()
    mock.system_metrics.enable_system_metrics_logging = MagicMock()
    mock.search_runs = MagicMock()
    mock.models = MagicMock()
    mock.models.signature = MagicMock()
    mock.models.signature.ModelSignature = MagicMock()
    mock.types = MagicMock()
    mock.types.schema = MagicMock()
    mock.types.schema.Schema = MagicMock()
    mock.types.schema.TensorSpec = MagicMock()

    sys.modules["mlflow"] = mock
    sys.modules["mlflow.tracking"] = mock.tracking
    sys.modules["mlflow.pytorch"] = mock.pytorch
    sys.modules["mlflow.system_metrics"] = mock.system_metrics
    sys.modules["mlflow.data"] = mock.data
    sys.modules["mlflow.models"] = mock.models
    sys.modules["mlflow.models.signature"] = mock.models.signature
    sys.modules["mlflow.types"] = mock.types
    sys.modules["mlflow.types.schema"] = mock.types.schema
    return mock


def _make_model() -> GlobalLSTM:
    return GlobalLSTM(
        n_features=ML_CONFIG.N_FEATURES,
        vocab_size=10,
        embed_dim=ML_CONFIG.EMBED_DIM,
        hidden_dim=ML_CONFIG.HIDDEN_DIM,
        n_layers=ML_CONFIG.N_LAYERS,
        dropout=ML_CONFIG.DROPOUT,
        n_classes=ML_CONFIG.N_CLASSES,
    )


@pytest.fixture(autouse=True)
def _mlflow_patch():
    """Ensure mlflow and boto3 are mocked before each test.

    Evicts modules that capture a stale mlflow reference at import time so
    each test gets a fresh mock chain.
    """
    mock = _mock_mlflow()
    sys.modules["boto3"] = MagicMock()
    for key in list(sys.modules.keys()):
        if key.startswith("ml."):
            del sys.modules[key]
    yield mock
    for key in list(sys.modules.keys()):
        if key.startswith("mlflow") or key == "boto3" or key.startswith("ml."):
            del sys.modules[key]


def test_init_sets_experiment() -> None:
    """Constructor calls set_tracking_uri and set_experiment."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager(experiment_name="test_experiment")
    assert mgr.experiment_name == "test_experiment"
    assert mgr.active_run is None


def test_start_run_returns_run_id() -> None:
    """start_run initialises a run and returns a non-empty run ID."""
    import mlflow

    from ml.mlflow_manager import MLflowManager

    class FakeRunInfo:
        run_id = "test_run_id_123"

    class FakeRun:
        info = FakeRunInfo()

    mlflow.start_run.return_value = FakeRun()

    mgr = MLflowManager()
    run_id = mgr.start_run(run_name="test_run")
    assert run_id == "test_run_id_123"
    assert mgr.active_run is not None


def test_end_run_clears_active_run() -> None:
    """end_run clears the active run reference."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    import mlflow

    class FakeRunInfo:
        run_id = "test_run_id"

    class FakeRun:
        info = FakeRunInfo()

    mlflow.start_run.return_value = FakeRun()
    mgr.start_run("test")
    mgr.end_run()
    assert mgr.active_run is None


def test_log_params_delegates() -> None:
    """log_params calls mlflow.log_params with the given dict."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    params = {"lr": 0.001, "dropout": 0.5}
    mgr.log_params(params)
    import mlflow

    mlflow.log_params.assert_called_once_with(params)


def test_log_metrics_delegates() -> None:
    """log_metrics calls mlflow.log_metrics with correct args."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    metrics = {"accuracy": 0.85}
    mgr.log_metrics(metrics, step=1)
    import mlflow

    mlflow.log_metrics.assert_called_once_with(metrics, step=1)


def test_log_artifact_delegates() -> None:
    """log_artifact calls mlflow.log_artifact."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    mgr.log_artifact("/tmp/test.png", artifact_path="plots")
    import mlflow

    mlflow.log_artifact.assert_called_once_with("/tmp/test.png", artifact_path="plots")


def test_set_champion_alias_calls_client() -> None:
    """set_champion_alias sets the champion alias via MlflowClient."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    mock_client = MagicMock()
    import mlflow

    mlflow.tracking.MlflowClient.return_value = mock_client

    mgr.set_champion_alias(model_name="GlobalLSTM", version="3")
    mock_client.set_registered_model_alias.assert_called_once_with("GlobalLSTM", "champion", "3")


def test_log_model_returns_run_id_and_version() -> None:
    """log_model returns (run_id, version) tuple."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    model = _make_model()

    import mlflow

    class FakeRunInfo:
        run_id = "run_abc"

    class FakeRun:
        info = FakeRunInfo()

    mlflow.start_run.return_value = FakeRun()
    mgr.start_run("test")

    mock_client = MagicMock()
    mock_client.search_model_versions.return_value = [
        MagicMock(version="1"),
        MagicMock(version="2"),
    ]
    mlflow.tracking.MlflowClient.return_value = mock_client

    run_id, version = mgr.log_model(model)
    assert run_id == "run_abc"
    assert version == "2"


def test_enable_autologging_delegates() -> None:
    """enable_autologging calls mlflow.pytorch.autolog."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    mgr.enable_autologging()
    import mlflow

    mlflow.pytorch.autolog.assert_called_once()


def test_cleanup_stale_runs_kills_running() -> None:
    """cleanup_stale_runs terminates RUNNING runs for the experiment."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    mock_client = MagicMock()
    mock_experiment = MagicMock()
    mock_experiment.experiment_id = "exp_1"
    mock_client.get_experiment_by_name.return_value = mock_experiment

    running_run = MagicMock()
    running_run.info.run_id = "stale_run_1"
    mock_client.search_runs.return_value = [running_run]

    import mlflow

    mlflow.tracking.MlflowClient.return_value = mock_client

    mgr.cleanup_stale_runs()
    mock_client.get_experiment_by_name.assert_called_once_with(mgr.experiment_name)
    mock_client.search_runs.assert_called_once()
    mock_client.set_terminated.assert_called_once_with("stale_run_1", status="KILLED")


def test_tag_best_run_flags_current() -> None:
    """tag_best_run returns True and tags when current run is best."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    import mlflow

    class FakeRunInfo:
        run_id = "best_run_id"

    class FakeRun:
        info = FakeRunInfo()

    mlflow.start_run.return_value = FakeRun()
    mgr.start_run("test")

    mock_client = MagicMock()
    mock_client.get_experiment_by_name.return_value = MagicMock(experiment_id="exp_1")
    import pandas as pd

    df = pd.DataFrame([{"run_id": "best_run_id", "metrics.accuracy": 0.95}])
    mlflow.search_runs.return_value = df

    mlflow.tracking.MlflowClient.return_value = mock_client

    result = mgr.tag_best_run(metric="accuracy")
    assert result is True
    mock_client.set_tag.assert_called()


@patch("ml.mlflow_manager.boto3")
def test_save_champion_to_disk_creates_file(mock_boto3: MagicMock) -> None:
    """save_champion_to_disk writes a model file and returns its path."""
    from ml.mlflow_manager import MLflowManager

    mgr = MLflowManager()
    model = _make_model()

    path = mgr.save_champion_to_disk(model)
    assert path.endswith("model.pt")
    import os

    assert os.path.exists(path)
    os.unlink(path)
