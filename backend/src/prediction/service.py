"""
Prediction service — model loading, feature computation, inference.

Loaded once at FastAPI startup via lifespan and reused across requests.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import torch

from ml.config import ML_CONFIG as ml_config
from ml.features import compute_all_features
from ml.model import GlobalLSTM

logger = structlog.get_logger()

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

    def _compute_features(self, ohlcv_rows: list[dict]) -> torch.Tensor | None:
        """Compute 30-day feature window from OHLCV data and standardise.

        Uses the global feature means/stds stored in the model checkpoint
        during training. Without standardisation, the model receives
        non-normalized inputs and produces degraded predictions.

        Args:
            ohlcv_rows: List of OHLCV dicts from market/repository.py.

        Returns:
            (1, 30, n_features) tensor ready for model input, or None if
            insufficient data.
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
        close = df["adjusted_close"].astype(float)

        # Compute features
        features_df = compute_all_features(pd.DataFrame({"adjusted_close": close}))

        # Take the last SEQUENCE_LENGTH rows
        feature_values = features_df.values[-ml_config.SEQUENCE_LENGTH :].astype(np.float32)

        # Handle NaN (shouldn't happen with 60+ days of data, but safeguard)
        feature_values = np.nan_to_num(feature_values, nan=0.0)

        # Apply z-score standardisation using training distribution params
        if (
            self.model is not None
            and self.model._feature_means is not None
            and self.model._feature_stds is not None
        ):
            means = self.model._feature_means
            stds = self.model._feature_stds
            feature_values = (feature_values - means) / stds
        else:
            # Fallback: per-batch standardisation
            logger.warning("no_stored_feature_stats_applying_per_batch_standardisation")
            batch_mean = np.nanmean(feature_values, axis=0)
            batch_std = np.nanstd(feature_values, axis=0)
            batch_std[batch_std == 0] = 1.0
            feature_values = (feature_values - batch_mean) / batch_std

        # Convert to tensor with batch dimension
        tensor = torch.tensor(feature_values, dtype=torch.float32).unsqueeze(0)
        return tensor

    def predict(self, ticker: str, ohlcv_rows: list[dict]) -> dict | None:
        """Run prediction for a single ticker.

        Args:
            ticker: Ticker symbol (for embedding lookup).
            ohlcv_rows: List of OHLCV dicts (90+ days).

        Returns:
            Dict with keys: direction, confidence, probabilities, model_version.
            None if prediction cannot be made.
        """
        if self.model is None:
            logger.error("model_not_loaded_cannot_predict")
            return None

        # Get ticker embedding index from model's stored vocabulary
        vocab = getattr(self.model, "_vocab", {})
        ticker_idx_val = vocab.get(ticker.upper(), 0)  # 0 = UNK_IDX
        ticker_idx = torch.tensor([ticker_idx_val], dtype=torch.long)

        # Compute features
        features = self._compute_features(ohlcv_rows)
        if features is None:
            return None

        # Run inference
        with torch.no_grad():
            features = features.to(self.device)
            ticker_idx = ticker_idx.to(self.device)
            logits = self.model(features, ticker_idx)
            probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]

        # Parse results
        pred_class = int(np.argmax(probs))
        confidence = float(probs[pred_class])
        probabilities = {CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))}

        return {
            "ticker": ticker.upper(),
            "direction": CLASS_NAMES[pred_class],
            "confidence": confidence,
            "probabilities": probabilities,
            "model_version": self.model_version,
        }


# Singleton instance — created at module level, loaded in lifespan
prediction_service = PredictionService()
