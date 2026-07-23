"""Unit tests for prediction/service.py — PredictionService class.

Uses mocks for torch, pandas, and the ML module to avoid loading real models
or requiring GPU. The singleton (prediction_service) is reset between tests.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
import torch

from src.prediction.service import PredictionService

# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def service():
    """Return a fresh PredictionService instance (no model loaded)."""
    svc = PredictionService()
    yield svc
    # Clean up any model reference
    svc.model = None


@pytest.fixture
def mock_global_lstm():
    """Create a mock GlobalLSTM model with required attributes."""
    model = Mock()
    model._model_version = "test-v1"
    model._vocab = {"AAPL": 1, "MSFT": 2, "SPY": 3}
    model._feature_means = np.zeros(17, dtype=np.float32)
    model._feature_stds = np.ones(17, dtype=np.float32)

    def mock_forward(features, ticker_idx):
        """Return logits: [batch, 3] for 3 classes."""
        batch_size = features.shape[0]
        return torch.tensor([[0.1, 2.0, 0.3]] * batch_size, dtype=torch.float32)

    model.side_effect = mock_forward
    return model


@pytest.fixture
def ohlcv_rows():
    """Generate 150 days of OHLCV data for a ticker."""
    np.random.seed(42)
    n = 150
    dates = pd.date_range(end="2024-12-31", periods=n)
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return [
        {
            "date": d,
            "adjusted_close": float(prices[i]),
            "high": float(prices[i] * 1.02),
            "low": float(prices[i] * 0.98),
            "volume": int(1_000_000 + np.random.randint(0, 500_000)),
            "open": float(prices[i] * 0.99),
        }
        for i, d in enumerate(dates)
    ]


# ── load_model ──────────────────────────────────────────────────────────────────


class TestLoadModel:
    """PredictionService.load_model loads champion model from disk."""

    def test_returns_false_when_file_not_found(self, service):
        result = service.load_model("/nonexistent/path/model.pt")
        assert result is False
        assert service.model is None

    @patch("src.prediction.service.Path.exists", return_value=True)
    @patch("src.prediction.service.GlobalLSTM")
    def test_loads_model_successfully(self, mock_global_lstm_cls, mock_exists, service):
        mock_model = Mock()
        mock_model._model_version = "v1.0"
        mock_global_lstm_cls.load.return_value = mock_model

        with patch("src.prediction.service.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            result = service.load_model("/models/champion.pt")

        assert result is True
        assert service.model is mock_model
        assert service.model_version == "v1.0"
        mock_model.to.assert_called_once()
        mock_model.eval.assert_called_once()

    @patch("src.prediction.service.Path.exists", return_value=True)
    @patch("src.prediction.service.GlobalLSTM")
    def test_handles_load_exception(self, mock_global_lstm_cls, mock_exists, service):
        mock_global_lstm_cls.load.side_effect = RuntimeError("corrupt checkpoint")

        with patch("src.prediction.service.Path"):
            result = service.load_model("/models/bad.pt")

        assert result is False
        assert service.model is None


# ── is_loaded ───────────────────────────────────────────────────────────────────


class TestIsLoaded:
    def test_returns_false_when_no_model(self, service):
        assert service.is_loaded() is False

    def test_returns_true_when_model_loaded(self, service, mock_global_lstm):
        service.model = mock_global_lstm
        assert service.is_loaded() is True


# ── _compute_padded_features ────────────────────────────────────────────────────


class TestComputePaddedFeatures:
    """_compute_padded_features extracts OHLCV columns and computes features."""

    @patch("src.prediction.service.compute_all_features")
    def test_constructs_correct_dataframe(self, mock_compute, service, ohlcv_rows):
        df = pd.DataFrame(ohlcv_rows)
        fake_features = pd.DataFrame(
            np.random.randn(len(df), 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute.return_value = fake_features

        result, n_dates = service._compute_padded_features(df)

        assert n_dates == len(df)
        assert "ticker" not in result.columns
        assert len(result) == len(df)

        # Verify compute_all_features received correct columns
        call_arg = mock_compute.call_args[0][0]
        assert "adjusted_close" in call_arg.columns
        assert "high" in call_arg.columns
        assert "low" in call_arg.columns
        assert "volume" in call_arg.columns


# ── _compute_vol_pct ────────────────────────────────────────────────────────────


class TestComputeVolPct:
    """_compute_vol_pct computes volatility percentile from close prices."""

    def test_returns_float32_array(self, service, ohlcv_rows):
        df = pd.DataFrame(ohlcv_rows)
        result = service._compute_vol_pct(df["adjusted_close"])

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert result.shape == (len(df), 1)

    def test_values_between_zero_and_one(self, service, ohlcv_rows):
        df = pd.DataFrame(ohlcv_rows)
        result = service._compute_vol_pct(df["adjusted_close"])

        assert np.all((result >= 0.0) & (result <= 1.0))

    def test_handles_constant_close_prices(self, service):
        close = pd.Series([100.0] * 100)
        result = service._compute_vol_pct(close)

        # Should not crash; all values in [0, 1]
        assert result.shape == (100, 1)
        assert result.dtype == np.float32
        assert np.all((result >= 0.0) & (result <= 1.0))


# ── _compute_features ───────────────────────────────────────────────────────────


class TestComputeFeatures:
    """_compute_features runs the full feature pipeline."""

    def test_returns_none_for_insufficient_data(self, service):
        short_data = [
            {"date": "2024-01-01", "adjusted_close": 100, "high": 101, "low": 99, "volume": 1000}
        ]
        result = service._compute_features(short_data)
        assert result is None

    @patch("src.prediction.service.compute_all_features")
    def test_returns_tensor_with_correct_shape(
        self, mock_compute_features, service, ohlcv_rows, mock_global_lstm
    ):
        service.model = mock_global_lstm
        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        result = service._compute_features(ohlcv_rows)

        assert result is not None
        tensor, raw_features, feature_window = result
        assert isinstance(tensor, torch.Tensor)
        assert tensor.shape == (1, 30, 17)  # batch=1, seq=30, features=17
        assert raw_features.shape[1] == 17
        assert feature_window.shape == (30, 17)

    @patch("src.prediction.service.compute_cross_sectional_features")
    @patch("src.prediction.service.compute_all_features")
    def test_includes_cross_sectional_features_with_spy(
        self, mock_compute_features, mock_cs, service, ohlcv_rows, mock_global_lstm
    ):
        service.model = mock_global_lstm
        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        spy_data = ohlcv_rows  # full length to match ticker feature rows
        mock_cs.return_value = pd.DataFrame(
            np.random.randn(len(ohlcv_rows), 3),
            columns=["excess_ret", "rel_strength", "beta"],
        )

        result = service._compute_features(ohlcv_rows, spy_ohlcv_rows=spy_data)

        assert result is not None
        tensor, raw_features, feature_window = result
        # 13 base features + 1 vol_pct + 3 cs = 17
        assert raw_features.shape[1] == 17


# ── predict ─────────────────────────────────────────────────────────────────────


class TestPredict:
    """PredictionService.predict runs full inference pipeline."""

    def test_returns_none_when_model_not_loaded(self, service, ohlcv_rows):
        result = service.predict("AAPL", ohlcv_rows)
        assert result is None

    @patch("src.prediction.service.compute_all_features")
    @patch("src.prediction.prediction_logger._logger_executor")
    def test_returns_prediction_dict(
        self, mock_executor, mock_compute_features, service, ohlcv_rows, mock_global_lstm
    ):
        service.model = mock_global_lstm
        service.model_version = mock_global_lstm._model_version
        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        result = service.predict("AAPL", ohlcv_rows)

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["direction"] in ("DOWN", "FLAT", "UP")
        assert 0.0 <= result["confidence"] <= 1.0
        assert set(result["probabilities"].keys()) == {"DOWN", "FLAT", "UP"}
        assert result["model_version"] == "test-v1"

    @patch("src.prediction.service.compute_all_features")
    @patch("src.prediction.prediction_logger._logger_executor")
    def test_logs_prediction_async(
        self, mock_executor, mock_compute_features, service, ohlcv_rows, mock_global_lstm
    ):
        service.model = mock_global_lstm
        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        result = service.predict("MSFT", ohlcv_rows)

        assert result is not None
        # Verify logging was submitted (fire-and-forget)
        mock_executor.submit.assert_called_once()

    @patch("src.prediction.service.compute_all_features")
    @patch("src.prediction.prediction_logger._logger_executor")
    def test_uses_unk_idx_for_unknown_ticker(
        self, mock_executor, mock_compute_features, service, ohlcv_rows, mock_global_lstm
    ):
        service.model = mock_global_lstm
        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        result = service.predict("UNKNOWN", ohlcv_rows)

        assert result is not None
        assert result["ticker"] == "UNKNOWN"


# ── _compute_features edge cases ────────────────────────────────────────────────


class TestComputeFeaturesEdgeCases:
    """Branch coverage for uncovered paths in _compute_features."""

    @patch("src.prediction.service.compute_cross_sectional_features")
    @patch("src.prediction.service.compute_all_features")
    def test_spy_cross_sectional_exception_handled(
        self, mock_compute_features, mock_cs, service, ohlcv_rows, mock_global_lstm
    ):
        """Lines 157-158: exception in cross-sectional features is caught gracefully."""
        service.model = mock_global_lstm
        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        # Cause cross_sectional_features to raise
        mock_cs.side_effect = RuntimeError("CS computation failed")

        # Generate valid SPY data (>= SEQUENCE_LENGTH + 30 rows)
        spy_data = ohlcv_rows  # 150 rows

        result = service._compute_features(ohlcv_rows, spy_ohlcv_rows=spy_data)

        # Should NOT crash; falls back to zero-padded cross-sectional features
        assert result is not None
        tensor, raw_features, feature_window = result
        assert raw_features.shape[1] == 17  # 13 base + 1 vol_pct + 3 zero-pad

    @patch("src.prediction.service.compute_all_features")
    def test_feature_count_mismatch_batch_norm(self, mock_compute_features, service, ohlcv_rows):
        """Lines 186-199: feature count mismatch triggers per-batch normalisation."""
        # Set up model with 14-element stats (mismatch from computed 17)
        mock_model = Mock()
        mock_model._model_version = "old-v13"
        mock_model._vocab = {"TEST": 1}
        mock_model._feature_means = np.zeros(14, dtype=np.float32)
        mock_model._feature_stds = np.ones(14, dtype=np.float32)

        def mock_fwd(*args, **kwargs):
            return torch.tensor([[0.1, 2.0, 0.3]], dtype=torch.float32)

        mock_model.side_effect = mock_fwd
        service.model = mock_model

        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        result = service._compute_features(ohlcv_rows)

        # Should NOT crash; uses per-batch normalisation
        assert result is not None
        tensor, raw_features, feature_window = result
        assert tensor.shape == (1, 30, 17)

    def test_returns_none_when_compute_features_fails(self, service):
        """Line 274: predict returns None when _compute_features returns None."""
        # Only 1 OHLCV row — not enough for SEQUENCE_LENGTH
        short_data = [
            {"date": "2024-01-01", "adjusted_close": 100, "high": 101, "low": 99, "volume": 1000}
        ]
        result = service.predict("AAPL", short_data)
        assert result is None


# ── SageMaker serving path ──────────────────────────────────────────────────────


class TestSageMakerPredict:
    """Coverage for _sagemaker_predict and the SageMaker serving path."""

    def test_sagemaker_predict_success(self, service):
        """Lines 233-251: successful SageMaker endpoint invocation."""
        feature_window = np.random.randn(30, 17).astype(np.float32)

        mock_sm = Mock()
        mock_response = {"Body": Mock()}
        mock_response["Body"].read.return_value = json.dumps(
            {
                "direction": "UP",
                "confidence": 0.85,
                "probabilities": {"DOWN": 0.05, "FLAT": 0.10, "UP": 0.85},
            }
        ).encode("utf-8")

        mock_sm.invoke_endpoint.return_value = mock_response

        with patch("src.prediction.service.boto3.client", return_value=mock_sm):
            result = service._sagemaker_predict("AAPL", feature_window)

        assert result is not None
        assert result["direction"] == "UP"
        assert result["confidence"] == 0.85
        assert result["model_version"] == "sagemaker"
        assert "UP" in result["probabilities"]

    def test_sagemaker_predict_failure_returns_none(self, service):
        """Lines 252-254: exception in SageMaker call returns None."""
        feature_window = np.random.randn(30, 17).astype(np.float32)

        with patch("src.prediction.service.boto3.client") as mock_client:
            mock_client.side_effect = ConnectionError("no route to host")
            result = service._sagemaker_predict("AAPL", feature_window)

        assert result is None

    @patch("src.prediction.service.compute_all_features")
    @patch("src.prediction.prediction_logger._logger_executor")
    @patch("src.prediction.service.settings")
    def test_predict_sagemaker_path(
        self,
        mock_settings,
        mock_executor,
        mock_compute_features,
        service,
        ohlcv_rows,
        mock_global_lstm,
    ):
        """Lines 279-299: SageMaker serving path with fire-and-forget logging."""
        mock_settings.PREDICTION_SERVING_BACKEND = "sagemaker"
        mock_settings.AWS_REGION = "us-east-1"
        mock_settings.SAGEMAKER_ENDPOINT_NAME = "test-endpoint"

        service.model = mock_global_lstm
        service.model_version = mock_global_lstm._model_version

        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        # Mock SageMaker response
        mock_sm = Mock()
        mock_response = {"Body": Mock()}
        mock_response["Body"].read.return_value = json.dumps(
            {
                "direction": "DOWN",
                "confidence": 0.72,
                "probabilities": {"DOWN": 0.72, "FLAT": 0.18, "UP": 0.10},
            }
        ).encode("utf-8")

        mock_sm.invoke_endpoint.return_value = mock_response

        with patch("src.prediction.service.boto3.client", return_value=mock_sm):
            result = service.predict("AAPL", ohlcv_rows)

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["direction"] in ("UP", "DOWN", "FLAT")
        assert result["model_version"] == "sagemaker"

        # Fire-and-forget logging submitted
        mock_executor.submit.assert_called_once()

    @patch("src.prediction.service.compute_all_features")
    @patch("src.prediction.service.settings")
    def test_sagemaker_prediction_fallback(
        self, mock_settings, mock_compute_features, service, ohlcv_rows, mock_global_lstm
    ):
        """Lines 282-284: SageMaker fails, predict returns None."""
        mock_settings.PREDICTION_SERVING_BACKEND = "sagemaker"
        mock_settings.AWS_REGION = "us-east-1"
        mock_settings.SAGEMAKER_ENDPOINT_NAME = "test-endpoint"

        service.model = mock_global_lstm
        service.model_version = mock_global_lstm._model_version

        df = pd.DataFrame(ohlcv_rows)
        n = len(df)
        fake_features = pd.DataFrame(
            np.random.randn(n, 13),
            columns=[f"feat_{i}" for i in range(13)],
        )
        fake_features["ticker"] = "TEST"
        mock_compute_features.return_value = fake_features

        with patch.object(service, "_sagemaker_predict", return_value=None):
            result = service.predict("AAPL", ohlcv_rows)

        assert result is None
