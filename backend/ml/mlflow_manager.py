"""
MLflow integration for experiment tracking and model registry.

Handles:
    - Run creation and management
    - Hyperparameter and metric logging
    - Artifact logging (loss curves, confusion matrix)
    - Model saving and registration
    - Champion model alias management
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import mlflow
import mlflow.pytorch
import numpy as np

from ml.config import ML_CONFIG
from ml.model import GlobalLSTM

logger = logging.getLogger(__name__)


class MLflowManager:
    """Manages MLflow runs and model registry operations."""

    def __init__(self, experiment_name: str = "stocklens_lstm") -> None:
        mlflow.set_tracking_uri(ML_CONFIG.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(experiment_name)
        self.experiment_name = experiment_name
        self.active_run: Optional[mlflow.ActiveRun] = None

    def start_run(self, run_name: Optional[str] = None) -> str:
        """Start a new MLflow run.

        Args:
            run_name: Optional human-readable run name.

        Returns:
            MLflow run ID.
        """
        self.active_run = mlflow.start_run(run_name=run_name)
        run_id = self.active_run.info.run_id
        logger.info("MLflow run started", extra={"run_id": run_id})
        return run_id

    def end_run(self) -> None:
        """End the active MLflow run."""
        if self.active_run:
            mlflow.end_run()
            logger.info("MLflow run ended")
            self.active_run = None

    def log_params(self, params: dict[str, Any]) -> None:
        """Log hyperparameters to the active run."""
        mlflow.log_params(params)

    def log_metrics(self, metrics: dict[str, float], step: Optional[int] = None) -> None:
        """Log metrics to the active run.

        Args:
            metrics: Dict of metric name to value.
            step: Optional step (epoch) number.
        """
        mlflow.log_metrics(metrics, step=step)

    def log_artifact(self, local_path: str, artifact_path: Optional[str] = None) -> None:
        """Log a local file as an artifact.

        Args:
            local_path: Path to local file.
            artifact_path: Optional subdirectory within artifact store.
        """
        mlflow.log_artifact(local_path, artifact_path=artifact_path)

    def log_model(
        self,
        model: GlobalLSTM,
        artifact_path: str = "model",
        registered_model_name: str = "GlobalLSTM",
    ) -> tuple[str, str]:
        """Log the PyTorch model to MLflow and register it.

        Args:
            model: Trained GlobalLSTM instance.
            artifact_path: Path within MLflow artifacts.
            registered_model_name: Name for Model Registry.

        Returns:
            (run_id, model_version) tuple.
        """
        # Log model using mlflow.pytorch
        mlflow.pytorch.log_model(
            pytorch_model=model,
            artifact_path=artifact_path,
            registered_model_name=registered_model_name,
            requirements_file=None,
        )

        # Get the registered model version
        client = mlflow.tracking.MlflowClient()
        model_version = client.get_latest_versions(
            registered_model_name,
            stages=["None"],
        )
        version = model_version[0].version if model_version else "1"

        run_id = self.active_run.info.run_id if self.active_run else "unknown"
        return run_id, version

    def set_champion_alias(self, model_name: str = "GlobalLSTM", version: str = "1") -> None:
        """Set the 'champion' alias on a model version.

        Args:
            model_name: Registered model name.
            version: Model version string.
        """
        client = mlflow.tracking.MlflowClient()
        client.set_registered_model_alias(model_name, "champion", version)
        logger.info(
            "Champion alias set",
            extra={"model_name": model_name, "version": version},
        )

    def save_champion_to_disk(
        self,
        model: GlobalLSTM,
        vocab: Optional[dict[str, int]] = None,
        feature_means: Optional[np.ndarray] = None,
        feature_stds: Optional[np.ndarray] = None,
    ) -> str:
        """Save champion model to the shared volume for backend inference.

        Uses atomic write (temp file + rename) so the backend never reads
        a partially-written model file. The checkpoint includes the ticker
        vocabulary and standardisation params so inference can re-apply the
        same transform.

        Args:
            model: Trained GlobalLSTM instance.
            vocab: Ticker-to-index vocabulary for entity embedding lookup.
            feature_means: Per-feature means (from global pooled z-score).
            feature_stds: Per-feature stds (from global pooled z-score).

        Returns:
            Path to the saved model file.
        """
        save_dir = Path(ML_CONFIG.MODEL_ARTIFACT_DIR)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(save_dir / "model.pt")

        # Write to a temp file in the same directory, then atomic rename
        fd, tmp_path = tempfile.mkstemp(dir=str(save_dir), suffix=".pt.tmp")
        try:
            model.save(
                tmp_path,
                vocab=vocab,
                feature_means=feature_means,
                feature_stds=feature_stds,
            )
            os.fsync(fd)  # flush OS buffer
            os.replace(tmp_path, save_path)  # atomic on POSIX, near-atomic on macOS
        finally:
            os.close(fd)
            # Clean up temp file if rename failed
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        logger.info("Champion model saved to disk (atomic)", extra={"path": save_path})
        return save_path
