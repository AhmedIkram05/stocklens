"""
Tests for the ML training pipeline orchestrator.

All tests mock external dependencies (asyncpg, mlflow, torch, yfinance).
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import torch

from ml.config import ML_CONFIG


def _mock_mlflow_module() -> MagicMock:
    """Patch sys.modules so mlflow imports don't fail."""
    mock = MagicMock()
    mock.set_tracking_uri = MagicMock()
    mock.set_experiment = MagicMock()
    mock.tracking.MlflowClient = MagicMock()
    mock.active_run = MagicMock()
    mock.start_run = MagicMock()
    mock.end_run = MagicMock()
    mock.log_params = MagicMock()
    mock.log_metrics = MagicMock()
    mock.log_artifact = MagicMock()
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


@pytest.fixture(autouse=True)
def _mlflow_patch():
    mock = _mock_mlflow_module()
    sys.modules["boto3"] = MagicMock()
    yield mock
    for key in list(sys.modules.keys()):
        if key.startswith("mlflow") or key == "boto3":
            del sys.modules[key]


# ---------------------------------------------------------------------------
# fetch_ohlcv_for_tickers
# ---------------------------------------------------------------------------


def _make_ohlcv_row(ticker: str, days: int, start_val: float = 100.0):
    """Create a mock asyncpg row with OHLCV columns."""
    import datetime

    date_val = datetime.date.today() - datetime.timedelta(days=days)
    open_val = start_val + days * 0.1
    high_val = open_val + 0.5
    low_val = open_val - 0.5
    close_val = open_val + 0.2
    adj_close_val = close_val
    volume_val = 1_000_000 + days

    def getitem(key):
        mapping = {
            "ticker": ticker,
            "date": date_val,
            "open": open_val,
            "high": high_val,
            "low": low_val,
            "close": close_val,
            "adjusted_close": adj_close_val,
            "volume": volume_val,
        }
        return mapping[key]

    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=getitem)
    row.__iter__ = MagicMock(
        return_value=iter(
            [  # Required for dict(row) and tuple unpacking
                ("ticker", ticker),
                ("date", date_val),
                ("open", open_val),
                ("high", high_val),
                ("low", low_val),
                ("close", close_val),
                ("adjusted_close", adj_close_val),
                ("volume", volume_val),
            ]
        )
    )
    return row


@pytest.mark.asyncio
async def test_fetch_ohlcv_for_tickers_returns_data() -> None:
    """fetch_ohlcv_for_tickers returns dict of ticker -> ndarray."""
    from ml.pipeline import fetch_ohlcv_for_tickers

    rows = [_make_ohlcv_row("AAPL", i) for i in range(100)]
    fake_conn = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=rows)
    fake_conn.close = AsyncMock()

    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        result = await fetch_ohlcv_for_tickers(["AAPL"])

    assert "AAPL" in result
    arr = result["AAPL"]
    assert len(arr) == 100
    assert arr.dtype.names == ("date", "open", "high", "low", "close", "adjusted_close", "volume")
    assert arr[0]["close"] > 0


@pytest.mark.asyncio
async def test_fetch_ohlcv_skips_tickers_with_few_days() -> None:
    """Tickers with fewer than MIN_OHLCV_DAYS are skipped."""
    from ml.pipeline import fetch_ohlcv_for_tickers

    few_rows = [_make_ohlcv_row("AAPL", 0)]
    fake_conn = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=few_rows)
    fake_conn.close = AsyncMock()

    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        result = await fetch_ohlcv_for_tickers(["AAPL"])

    assert "AAPL" not in result


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_empty_dict_when_no_data() -> None:
    """Empty DB result returns an empty dict."""
    from ml.pipeline import fetch_ohlcv_for_tickers

    fake_conn = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.close = AsyncMock()

    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        result = await fetch_ohlcv_for_tickers(["AAPL", "MSFT"])

    assert result == {}


# ---------------------------------------------------------------------------
# prepare_global_dataset
# ---------------------------------------------------------------------------


def _make_ohlcv_array(ticker: str, n_days: int = 200) -> np.ndarray:
    """Create a structured numpy array mimicking OHLCV data."""
    dtype = [
        ("date", "datetime64[D]"),
        ("open", "f8"),
        ("high", "f8"),
        ("low", "f8"),
        ("close", "f8"),
        ("adjusted_close", "f8"),
        ("volume", "i8"),
    ]
    import datetime

    data = []
    for i in range(n_days):
        d = datetime.date.today() - datetime.timedelta(days=n_days - i)
        close = 100.0 + i * 0.5 + (i % 10) * 0.3
        data.append((d, close - 0.5, close + 0.5, close - 1.0, close, close, 1_000_000 + i))
    return np.array(data, dtype=dtype)


def test_prepare_global_dataset_basic() -> None:
    """prepare_global_dataset returns sequences, labels, ticker_idxs."""
    from ml.pipeline import prepare_global_dataset

    tickers = ["AAPL", "MSFT"]
    data = {t: _make_ohlcv_array(t) for t in tickers}
    vocab = {"<UNK>": 0, "AAPL": 1, "MSFT": 2}

    seqs, labels, idxs = prepare_global_dataset(data, vocab, spy_features_df=None)
    assert len(seqs) > 0
    assert len(labels) == len(seqs)
    assert len(idxs) == len(seqs)
    assert seqs.shape[1] == ML_CONFIG.SEQUENCE_LENGTH
    assert seqs.shape[2] == 14  # 13 V1 + vol_pct (no cross-sectional)


def test_prepare_global_dataset_with_spy() -> None:
    """With SPY features, n_features becomes 17."""
    from ml.pipeline import prepare_global_dataset

    data = {"AAPL": _make_ohlcv_array("AAPL")}
    vocab = {"<UNK>": 0, "AAPL": 1}

    import pandas as pd

    dates = data["AAPL"]["date"]
    spy_df = pd.DataFrame(
        {
            "log_ret_1d": np.random.randn(len(dates)),
            "log_ret_5d": np.random.randn(len(dates)),
            "log_ret_21d": np.random.randn(len(dates)),
        },
        index=dates,
    )

    seqs, _, _ = prepare_global_dataset(data, vocab, spy_features_df=spy_df)
    assert seqs.shape[2] == 17  # 13 V1 + vol_pct + 3 excess returns


def test_prepare_global_dataset_empty_data() -> None:
    """Empty OHLCV data returns empty arrays."""
    from ml.pipeline import prepare_global_dataset

    seqs, labels, idxs = prepare_global_dataset({}, {})
    assert len(seqs) == 0
    assert len(labels) == 0
    assert len(idxs) == 0


# ---------------------------------------------------------------------------
# fit_normalize_splits
# ---------------------------------------------------------------------------


def test_fit_normalize_splits_returns_normalized_data() -> None:
    """fit_normalize_splits returns z-scored train/val/test + means/stds."""
    from ml.pipeline import fit_normalize_splits

    rng = np.random.default_rng(42)
    train = (rng.normal(5, 2, (100, 30, 3)), np.zeros(100), np.zeros(100))
    val = (rng.normal(5, 2, (20, 30, 3)), np.zeros(20), np.zeros(20))
    test = (rng.normal(5, 2, (20, 30, 3)), np.zeros(20), np.zeros(20))

    (train_n, val_n, test_n, means, stds) = fit_normalize_splits(train, val, test)

    assert train_n[0].shape == train[0].shape
    assert val_n[0].shape == val[0].shape
    assert test_n[0].shape == test[0].shape
    assert means.shape == (3,)
    assert stds.shape == (3,)
    # Training data should be approximately mean 0 std 1 after z-score
    assert abs(train_n[0].mean()) < 1.0
    assert abs(train_n[0].std() - 1.0) < 0.5


def test_fit_normalize_splits_zero_stds_handled() -> None:
    """Features with zero std are set to 1.0 to avoid division by zero."""
    from ml.pipeline import fit_normalize_splits

    train = (np.ones((50, 10, 3)), np.zeros(50), np.zeros(50))
    val = (np.ones((10, 10, 3)), np.zeros(10), np.zeros(10))
    test = (np.ones((10, 10, 3)), np.zeros(10), np.zeros(10))

    _, _, _, means, stds = fit_normalize_splits(train, val, test)
    assert np.all(stds > 0)


# ---------------------------------------------------------------------------
# _record_in_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_in_db_inserts_row() -> None:
    """_record_in_db updates champion and inserts new record."""
    from ml.pipeline import _record_in_db

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()
    fake_conn.close = AsyncMock()
    fake_tx = AsyncMock()
    fake_conn.transaction = MagicMock(return_value=fake_tx)

    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        await _record_in_db("run_1", "v1", {"accuracy": 0.85})

    fake_conn.execute.assert_any_call(
        "UPDATE model_registry SET alias = NULL WHERE alias = 'champion'",
    )


# ---------------------------------------------------------------------------
# run_pipeline (end-to-end skeleton)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_no_data_returns_error() -> None:
    """run_pipeline returns error dict when no OHLCV data fetched."""
    from ml.pipeline import run_pipeline

    fake_conn = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.close = AsyncMock()

    with (
        patch("asyncpg.connect", AsyncMock(return_value=fake_conn)),
        patch("ml.pipeline.set_seed"),
        patch("ml.pipeline.get_device", return_value=torch.device("cpu")),
    ):
        result = await run_pipeline()

    assert "error" in result
    assert result["error"] == 1.0


# ---------------------------------------------------------------------------
# Champion gate wiring — every pipeline stage mocked except the gate itself
# ---------------------------------------------------------------------------


@contextmanager
def _pipeline_up_to_gate(*, champion_da: float | None, test_metrics: dict):
    """Run run_pipeline with all stages stubbed; yields (mlflow_mgr, recorders)."""
    mgr = MagicMock()
    mgr.read_champion_metrics = AsyncMock(
        return_value=None if champion_da is None else {"directional_accuracy": champion_da}
    )
    rec_champion = AsyncMock()
    rec_challenger = AsyncMock()

    seqs = np.zeros((120, 30, ML_CONFIG.N_FEATURES), dtype=np.float32)
    labels = np.zeros(120, dtype=np.int64)
    idxs = np.zeros(120, dtype=np.int64)
    split = (
        (seqs[:70], labels[:70], idxs[:70]),
        (seqs[70:90], labels[70:90], idxs[70:90]),
        (seqs[90:], labels[90:], idxs[90:]),
    )

    with (
        patch("asyncpg.connect", AsyncMock()),
        patch("ml.pipeline.set_seed"),
        patch("ml.pipeline.get_device", return_value=torch.device("cpu")),
        patch(
            "ml.pipeline.fetch_ohlcv_for_tickers",
            AsyncMock(side_effect=[{"AAA": np.zeros(10)}, {}]),  # data, then no SPY
        ),
        patch("ml.pipeline.build_ticker_vocabulary", return_value=({"AAA": 0}, 1)),
        patch("ml.pipeline.prepare_global_dataset", return_value=(seqs, labels, idxs)),
        patch("ml.pipeline.chronological_split", return_value=split),
        patch(
            "ml.pipeline.fit_normalize_splits",
            return_value=(split[0], split[1], split[2], np.zeros(1), np.ones(1)),
        ),
        patch(
            "ml.pipeline._run_lstm_pipeline",
            AsyncMock(return_value=(test_metrics, "v1", MagicMock(), "run_1")),
        ),
        patch("ml.pipeline.MLflowManager", return_value=mgr),
        patch("ml.pipeline._record_in_db", rec_champion),
        patch("ml.pipeline._record_challenger_in_db", rec_challenger),
        patch(
            "ml.reference_distributions.build_reference_from_training_data",
            return_value={},
        ),
        patch("ml.reference_distributions.store_reference_in_db", AsyncMock()),
    ):
        yield mgr, rec_champion, rec_challenger


@pytest.mark.asyncio
async def test_gate_blocks_noisy_improvement() -> None:
    """+2.5pp on n=200 is noise (p≈0.26): challenger recorded, champion kept."""
    from ml.pipeline import run_pipeline

    metrics = {
        "directional_accuracy": 0.525,
        "n_directional": 200,
        "n_directional_correct": 105,
    }
    with _pipeline_up_to_gate(champion_da=0.50, test_metrics=metrics) as (
        mgr,
        rec_champion,
        rec_challenger,
    ):
        result = await run_pipeline()

    assert result["directional_accuracy"] == 0.525
    logged = mgr.log_metrics.call_args[0][0]
    assert logged["promotion_p_value"] == pytest.approx(0.26, abs=0.05)
    assert logged["promotion_n_directional"] == 200.0
    tags = mgr.set_registered_model_tags.call_args[0][0]
    assert tags["promotion_reason"] == "not-significant"
    assert tags["promoted"] == "false"
    mgr.set_champion_alias.assert_not_called()
    rec_challenger.assert_awaited_once()
    rec_champion.assert_not_called()


@pytest.mark.asyncio
async def test_gate_promotes_significant_gain() -> None:
    """+5pp on n=2000 is real (p≪0.05): champion alias moves, reason tagged."""
    from ml.pipeline import run_pipeline

    metrics = {
        "directional_accuracy": 0.55,
        "n_directional": 2000,
        "n_directional_correct": 1100,
    }
    with _pipeline_up_to_gate(champion_da=0.50, test_metrics=metrics) as (
        mgr,
        rec_champion,
        rec_challenger,
    ):
        result = await run_pipeline()

    assert result["directional_accuracy"] == 0.55
    assert mgr.log_metrics.call_args[0][0]["promotion_p_value"] < 0.05
    tags = mgr.set_registered_model_tags.call_args[0][0]
    assert tags["promotion_reason"] == "significant"
    assert tags["promoted"] == "true"
    mgr.set_champion_alias.assert_called_once()
    rec_champion.assert_awaited_once()
    rec_challenger.assert_not_called()
