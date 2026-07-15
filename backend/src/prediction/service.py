"""
Prediction service — model loading, feature computation, inference.

Loaded once at FastAPI startup via lifespan and reused across requests.
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import structlog
import torch

from ml.config import ML_CONFIG as ml_config
from ml.features import compute_all_features, compute_cross_sectional_features
from ml.model import GlobalLSTM
from src.config import settings

logger = structlog.get_logger()

# Thread pool executor for fire-and-forget prediction logging
_logger_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

CLASS_NAMES = ("DOWN", "FLAT", "UP")


class PredictionService:
    """Singleton prediction service loaded at startup.

    Loads the champion GlobalLSTM model from the shared artifacts volume
    and performs inference on demand.
    """

    def __init__(self) -> None:
        self.model: GlobalLSTM | None = None
        self.model_version: str = "0"
        self.device = torch.device("cpu")  # Inference always on CPU
        self._feature_means: np.ndarray | None = None
        self._feature_stds: np.ndarray | None = None
        self._vocab: dict[str, int] | None = None

    def load_model(self, model_path: str = "/model_artifacts/champion/model.pt") -> bool:
        """Load champion model from disk.

        Args:
            model_path: Path to the saved model .pt file.

        Returns:
            True if model loaded successfully, False otherwise.
        """
        path = Path(model_path)
        if not path.exists():
            logger.warning("no_champion_model_found", path=model_path)
            return False

        try:
            self.model = GlobalLSTM.load(str(path), device=self.device)
            self.model.to(self.device)
            self.model.eval()
            self.model_version = self.model._model_version
            logger.info("champion_model_loaded", path=model_path, version=self.model_version)
            return True
        except Exception as exc:
            logger.exception("failed_to_load_champion_model", error=str(exc))
            return False

    def is_loaded(self) -> bool:
        """Check if model is loaded and ready."""
        return self.model is not None

    def _compute_padded_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        """Compute V1 features from a ticker OHLCV DataFrame, returning
        NaN-padded full-length DataFrame plus the time-aligned length.

        Constructs the full-COLUMN DataFrame the Rust engine expects
        (adjusted_close, high, low, volume), runs compute_all_features,
        returns the result with a date index for SPY alignment.
        """
        feature_df = pd.DataFrame(
            {
                "adjusted_close": df["adjusted_close"].astype(float),
                "high": df["high"].astype(float),
                "low": df["low"].astype(float),
                "volume": df["volume"].astype(float),
            }
        )
        features_df = compute_all_features(feature_df)
        # Drop ticker column if present
        named = features_df.drop(columns=["ticker"], errors="ignore")
        return named, len(named)

    def _compute_vol_pct(self, close_series: pd.Series) -> np.ndarray:
        """Compute vol percentile (14th feature) for a ticker's close series."""
        daily_log_ret = np.log(close_series / close_series.shift(1))
        rolling_vol = daily_log_ret.rolling(window=ml_config.SEQUENCE_LENGTH).std()
        vol_pct = rolling_vol.rank(pct=True).values.astype(np.float32)[:, np.newaxis]
        vol_pct = np.nan_to_num(vol_pct, nan=0.5)
        return vol_pct

    def _compute_features(
        self, ohlcv_rows: list[dict], spy_ohlcv_rows: list[dict] | None = None
    ) -> tuple[torch.Tensor, np.ndarray | None, np.ndarray | None] | None:
        """Compute feature window from OHLCV data and standardise.

        When ``spy_ohlcv_rows`` is provided, also computes cross-sectional
        features (excess returns vs SPY) for the feature window.

        Args:
            ohlcv_rows: List of OHLCV dicts for the target ticker.
            spy_ohlcv_rows: Optional list of SPY OHLCV dicts for
                cross-sectional features.

        Returns:
            ``(tensor, raw_feature_values, feature_window)`` where:
            - ``tensor``: (1, 30, n_features) tensor ready for model input
            - ``raw_feature_values``: (T, n_features) pre-standardisation raw features
            - ``feature_window``: (30, n_features) standardised sliding window
            Returns None if insufficient data.
        """
        if len(ohlcv_rows) < ml_config.SEQUENCE_LENGTH + 30:
            logger.warning(
                "insufficient_ohlcv_data",
                rows=len(ohlcv_rows),
                required=ml_config.SEQUENCE_LENGTH + 30,
            )
            return None

        # Convert to DataFrame and sort chronologically
        df = pd.DataFrame(ohlcv_rows).sort_values("date")
        close_series = df["adjusted_close"].astype(float)

        # 1. Compute V1 features
        ticker_features, n_dates = self._compute_padded_features(df)

        # 2. Compute vol_pct
        vol_pct = self._compute_vol_pct(close_series)  # (T, 1)

        # 3. Compute cross-sectional features if SPY data available
        spy_features = None
        if spy_ohlcv_rows is not None and len(spy_ohlcv_rows) >= ml_config.SEQUENCE_LENGTH + 30:
            try:
                spy_df = pd.DataFrame(spy_ohlcv_rows).sort_values("date")
                spy_named, _ = self._compute_padded_features(spy_df)
                # Align by date — take the last n_dates rows from SPY
                spy_aligned = spy_named.iloc[-n_dates:]
                spy_aligned.index = ticker_features.index[-len(spy_aligned) :]
                excess = compute_cross_sectional_features(ticker_features, spy_aligned)
                excess_values = excess.values.astype(np.float32)
                excess_values = np.nan_to_num(excess_values, nan=0.0)
                spy_features = excess_values
            except Exception as exc:
                logger.warning("cross_sectional_features_failed", error=str(exc))

        # 4. Concatenate features — ALWAYS produce 17 features (13 V1 + vol_pct + 3 excess)
        if spy_features is not None:
            feature_values = np.concatenate(
                [ticker_features.values.astype(np.float32), vol_pct, spy_features],
                axis=-1,
            )
        else:
            # Pad cross-sectional features with zeros to maintain 17-feature contract
            excess_pad = np.zeros((ticker_features.shape[0], 3), dtype=np.float32)
            feature_values = np.concatenate(
                [ticker_features.values.astype(np.float32), vol_pct, excess_pad],
                axis=-1,
            )

        # Save pre-standardisation raw features for drift logging
        raw_feature_values = feature_values.copy()

        # 5. Standardise using training stats
        if (
            self.model is not None
            and self.model._feature_means is not None
            and self.model._feature_stds is not None
        ):
            means = self.model._feature_means
            stds = self.model._feature_stds
            # Handle feature count mismatch (14 vs 17)
            if len(means) != feature_values.shape[-1]:
                logger.warning(
                    "feature_count_mismatch",
                    stored=len(means),
                    computed=feature_values.shape[-1],
                )
                # Use per-batch normalisation
                batch_mean = np.nanmean(feature_values, axis=0)
                batch_std = np.nanstd(feature_values, axis=0)
                batch_std[batch_std == 0] = 1.0
                feature_values = (feature_values - batch_mean) / batch_std
            else:
                feature_values = (feature_values - means) / stds
        else:
            # Fallback: per-batch standardisation
            logger.warning("no_stored_feature_stats_applying_per_batch_standardisation")
            batch_mean = np.nanmean(feature_values, axis=0)
            batch_std = np.nanstd(feature_values, axis=0)
            batch_std[batch_std == 0] = 1.0
            feature_values = (feature_values - batch_mean) / batch_std

        feature_values = np.nan_to_num(feature_values, nan=0.0)

        # 6. Take last SEQUENCE_LENGTH rows and add batch dim
        feature_window = feature_values[-ml_config.SEQUENCE_LENGTH :]
        tensor = torch.tensor(feature_window, dtype=torch.float32).unsqueeze(0)
        return tensor, raw_feature_values, feature_window

    def _sagemaker_predict(self, ticker: str, feature_window: np.ndarray) -> dict | None:
        """Invoke SageMaker serverless endpoint for prediction.

        Args:
            ticker: Ticker symbol (for request context).
            feature_window: (30, n_features) standardised sliding window.

        Returns:
            Dict with keys: direction, confidence, probabilities, model_version.
            None if SageMaker call fails.
        """
        endpoint_name = settings.SAGEMAKER_ENDPOINT_NAME
        payload = {
            "ticker": ticker.upper(),
            "features": feature_window.tolist(),
        }
        try:
            sm_client = boto3.client(
                "sagemaker-runtime",
                region_name=settings.AWS_REGION,
            )
            response = sm_client.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType="application/json",
                Body=json.dumps(payload),
            )
            result = json.loads(response["Body"].read().decode("utf-8"))
            # Expected shape: {direction, confidence, probabilities}
            result["model_version"] = "sagemaker"
            return result
        except Exception as exc:
            logger.exception("sagemaker_invoke_failed", ticker=ticker, error=str(exc))
            return None

    def predict(
        self, ticker: str, ohlcv_rows: list[dict], spy_ohlcv_rows: list[dict] | None = None
    ) -> dict | None:
        """Run prediction for a single ticker.

        Args:
            ticker: Ticker symbol (for embedding lookup).
            ohlcv_rows: List of OHLCV dicts (90+ days).
            spy_ohlcv_rows: Optional list of SPY OHLCV dicts for
                cross-sectional features.

        Returns:
            Dict with keys: direction, confidence, probabilities, model_version.
            None if prediction cannot be made.
        """
        # Compute features (shared between fargate and sagemaker paths)
        result = self._compute_features(ohlcv_rows, spy_ohlcv_rows)
        if result is None:
            return None

        features_tensor, raw_feature_values, feature_window = result

        # ── SageMaker serving path ──
        if settings.PREDICTION_SERVING_BACKEND == "sagemaker":
            logger.info("using_sagemaker_backend", ticker=ticker)
            sm_result = self._sagemaker_predict(ticker, feature_window)
            if sm_result is None:
                logger.error("sagemaker_prediction_failed_falling_back")
                return None

            # Fire-and-forget: log prediction for drift monitoring
            from src.prediction.prediction_logger import _logger_executor, log_prediction_sync

            _logger_executor.submit(
                log_prediction_sync,
                ticker,
                sm_result.get("model_version", "sagemaker"),
                sm_result["direction"],
                sm_result["confidence"],
                sm_result["probabilities"],
                raw_feature_values,
                feature_window,
            )
            return {
                "ticker": ticker.upper(),
                "direction": sm_result["direction"],
                "confidence": sm_result["confidence"],
                "probabilities": sm_result["probabilities"],
                "model_version": sm_result.get("model_version", "sagemaker"),
            }

        # ── Default Fargate serving path (local GlobalLSTM) ──
        if self.model is None:
            logger.error("model_not_loaded_cannot_predict")
            return None

        # Get ticker embedding index from model's stored vocabulary
        vocab = getattr(self.model, "_vocab", {})
        ticker_idx_val = vocab.get(ticker.upper(), 0)  # 0 = UNK_IDX
        ticker_idx = torch.tensor([ticker_idx_val], dtype=torch.long)

        # Run inference
        with torch.no_grad():
            features_tensor = features_tensor.to(self.device)
            ticker_idx = ticker_idx.to(self.device)
            logits = self.model(features_tensor, ticker_idx)
            probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]

        # Parse results
        pred_class = int(np.argmax(probs))
        confidence = float(probs[pred_class])
        probabilities = {CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))}

        # Fire-and-forget: log prediction for drift monitoring
        from src.prediction.prediction_logger import _logger_executor, log_prediction_sync

        _logger_executor.submit(
            log_prediction_sync,
            ticker,
            self.model_version,
            CLASS_NAMES[pred_class],
            confidence,
            probabilities,
            raw_feature_values,  # Full (T, 17) pre-window matrix
            feature_window,  # (30, 17) actual model input
        )

        return {
            "ticker": ticker.upper(),
            "direction": CLASS_NAMES[pred_class],
            "confidence": confidence,
            "probabilities": probabilities,
            "model_version": self.model_version,
        }


# Singleton instance — created at module level, loaded in lifespan
prediction_service = PredictionService()
