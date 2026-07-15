"""
MLflow integration for experiment tracking and model registry.

Handles:
    - Run creation and management
    - Hyperparameter and metric logging
    - Artifact logging (loss curves, confusion matrix)
    - Model saving and registration with signature
    - Champion model alias management
    - Autologging, system metrics, dataset tracking
    - Run/model/experiment descriptions and tags
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import boto3
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

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def cleanup_stale_runs(self) -> None:
        """Abort any RUNNING or SCHEDULED runs for this experiment.

        Handles the case where a previous training process was killed before
        ``mlflow.end_run()`` could execute (e.g. Docker container hard-kill).
        """
        client = mlflow.tracking.MlflowClient()
        experiment = client.get_experiment_by_name(self.experiment_name)
        if not experiment:
            return

        for run in client.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string="attributes.status = 'RUNNING'",
        ):
            client.set_terminated(run.info.run_id, status="KILLED")
            logger.warning("Killed stale MLflow run", extra={"run_id": run.info.run_id})

    def start_run(self, run_name: Optional[str] = None) -> str:
        """Start a new MLflow run.

        Args:
            run_name: Optional human-readable run name.

        Returns:
            MLflow run ID.
        """
        self.cleanup_stale_runs()
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

    # ------------------------------------------------------------------
    # Logging primitives
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Autologging & system metrics
    # ------------------------------------------------------------------

    def enable_autologging(self) -> None:
        """Enable PyTorch autologging.

        Logs model architecture, optimizer, gradients, and loss automatically.
        Disabled: model logging (we do it manually with registry) and dataset
        logging (we do it manually with richer context).
        """
        mlflow.pytorch.autolog(
            log_models=False,
            log_datasets=False,
            disable_for_unsupported_versions=False,
            silent=True,
        )
        logger.info("PyTorch autologging enabled")

    def enable_system_metrics(self) -> None:
        """Enable system metrics logging (CPU, memory, disk I/O)."""
        mlflow.system_metrics.enable_system_metrics_logging()
        logger.info("System metrics logging enabled")

    # ------------------------------------------------------------------
    # Dataset tracking
    # ------------------------------------------------------------------

    def log_dataset(
        self,
        data: np.ndarray,
        name: str = "dataset",
        context: str = "train",
    ) -> None:
        """Log dataset information to the active run.

        Args:
            data: NumPy array representing features or labels.
            name: Human-readable dataset name.
            context: Dataset role — ``"train"``, ``"val"``, or ``"test"``.
        """
        dataset = mlflow.data.from_numpy(data, name=name)
        mlflow.log_input(dataset, context=context)

    # ------------------------------------------------------------------
    # Descriptions
    # ------------------------------------------------------------------

    def set_run_description(self, description: str) -> None:
        """Set a human-readable description for the current run.

        Args:
            description: Free-text description of the run.
        """
        mlflow.set_tag("mlflow.note.content", description)

    def set_model_description(self, model_name: str, description: str) -> None:
        """Set the description for a registered model.

        Args:
            model_name: Registered model name (e.g. ``"GlobalLSTM"``).
            description: Free-text description.
        """
        client = mlflow.tracking.MlflowClient()
        client.update_registered_model(name=model_name, description=description)
        logger.info("Model description set", extra={"model": model_name})

    # ------------------------------------------------------------------
    # Model logging with signature
    # ------------------------------------------------------------------

    def log_model(
        self,
        model: GlobalLSTM,
        artifact_path: str = "model",
        registered_model_name: str = "GlobalLSTM",
    ) -> tuple[str, str]:
        """Log the PyTorch model to MLflow and register it.

        Includes an input/output schema (signature) for model serving
        compatibility.

        Args:
            model: Trained GlobalLSTM instance.
            artifact_path: Path within MLflow artifacts.
            registered_model_name: Name for Model Registry.

        Returns:
            (run_id, model_version) tuple.
        """
        from mlflow.models.signature import ModelSignature
        from mlflow.types.schema import Schema, TensorSpec

        input_schema = Schema(
            [
                TensorSpec(
                    np.dtype(np.float32),
                    (-1, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES),
                    "features",
                ),
                TensorSpec(np.dtype(np.int64), (-1,), "ticker_idxs"),
            ]
        )
        output_schema = Schema(
            [
                TensorSpec(np.dtype(np.float32), (-1, ML_CONFIG.N_CLASSES), "logits"),
            ]
        )
        signature = ModelSignature(inputs=input_schema, outputs=output_schema)

        # Move model to CPU for serialization (MPS tensors can't be pickled)
        model = model.cpu()

        mlflow.pytorch.log_model(
            pytorch_model=model,
            name=artifact_path,
            registered_model_name=registered_model_name,
            serialization_format="pickle",
            signature=signature,
        )

        # Get the registered model version via search (stages are deprecated in 3.x)
        client = mlflow.tracking.MlflowClient()
        versions = client.search_model_versions(
            f"name='{registered_model_name}'",
        )
        if versions:
            version = str(max(int(v.version) for v in versions))
        else:
            version = "1"

        run_id = self.active_run.info.run_id if self.active_run else "unknown"
        return run_id, version

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------

    def set_champion_alias(self, model_name: str = "GlobalLSTM", version: str = "1") -> None:
        """Set the ``'champion'`` alias on a model version.

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

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def set_registered_model_tags(
        self,
        tags: dict[str, str],
        model_name: str = "GlobalLSTM",
    ) -> None:
        """Set tags on the registered model.

        Args:
            tags: Key-value pairs (e.g. ``{"problem_type": "classification"}``).
            model_name: Registered model name.
        """
        client = mlflow.tracking.MlflowClient()
        for key, value in tags.items():
            client.set_registered_model_tag(model_name, key, value)
        logger.info("Registered model tags set", extra={"tags": tags})

    def set_experiment_tags(self, tags: dict[str, str]) -> None:
        """Set tags on the experiment.

        Args:
            tags: Key-value pairs (e.g. ``{"problem_type": "classification"}``).
        """
        client = mlflow.tracking.MlflowClient()
        experiment = client.get_experiment_by_name(self.experiment_name)
        if experiment:
            for key, value in tags.items():
                client.set_experiment_tag(experiment.experiment_id, key, value)
        logger.info("Experiment tags set", extra={"tags": tags})

    def tag_best_run(self, metric: str = "test_accuracy") -> bool:
        """Find the best run in this experiment by *metric* and tag it.

        Sets ``best_run=true``, ``best_metric=<metric>``, and
        ``best_value=<value>`` tags on the top run.

        Args:
            metric: Metric name to rank by (descending).

        Returns:
            True if the current run IS the best run, False otherwise.
        """
        client = mlflow.tracking.MlflowClient()
        experiment = client.get_experiment_by_name(self.experiment_name)
        if not experiment:
            logger.warning("Experiment %s not found — skipping best-run tag", self.experiment_name)
            return False

        runs = mlflow.search_runs(
            experiment_ids=[experiment.experiment_id],
            order_by=[f"metrics.{metric} DESC"],
            max_results=1,
        )
        if runs.empty:
            logger.warning("No runs found — skipping best-run tag")
            return False

        best_run = runs.iloc[0]
        best_run_id = best_run.get("run_id")

        if not best_run_id or not isinstance(best_run_id, str):
            logger.warning("Invalid run_id in search results — skipping best-run tag")
            return False

        best_value = best_run.get(f"metrics.{metric}", "unknown")

        client.set_tag(best_run_id, "best_run", "true")
        client.set_tag(best_run_id, "best_metric", metric)
        client.set_tag(best_run_id, "best_value", str(best_value))

        # Also tag the current run as comparison
        if self.active_run:
            current_id = self.active_run.info.run_id
            if current_id == best_run_id:
                client.set_tag(current_id, "run_quality", "best")
                return True
            else:
                client.set_tag(current_id, "run_quality", "challenger")
                client.set_tag(
                    current_id,
                    "delta_from_best",
                    str(best_value),
                )
                return False

        logger.info(
            "Best-run tag set",
            extra={"run_id": best_run_id, "metric": metric, "value": best_value},
        )

        return False

    # ------------------------------------------------------------------
    # Champion metrics
    # ------------------------------------------------------------------

    async def read_champion_metrics(self) -> dict[str, Any] | None:
        """Read champion metrics from the model_registry DB table.

        Reads the ``metrics`` JSONB column from the ``model_registry`` table
        where ``alias = 'champion'``.  Returns the raw ``test_metrics`` dict
        (with key ``directional_accuracy``), or ``None`` if no champion exists.

        Returns:
            Dict of metric name → value (e.g. ``{"directional_accuracy": 0.52}``),
            or ``None`` if there is no champion.
        """
        import asyncpg

        dsn = ML_CONFIG.SYNC_DATABASE_URL
        conn = await asyncpg.connect(dsn)
        try:
            await conn.set_type_codec(
                "jsonb",
                encoder=json.dumps,
                decoder=json.loads,
                schema="pg_catalog",
            )
            row = await conn.fetchrow(
                "SELECT metrics FROM model_registry WHERE alias = 'champion'",
            )
            if row and row["metrics"]:
                logger.info(
                    "Champion metrics read from DB",
                    extra={"directional_accuracy": row["metrics"].get("directional_accuracy")},
                )
                return row["metrics"]
            logger.info("No champion row found in model_registry")
            return None
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def save_champion_to_disk(
        self,
        model: GlobalLSTM,
        vocab: Optional[dict[str, int]] = None,
        feature_means: Optional[np.ndarray] = None,
        feature_stds: Optional[np.ndarray] = None,
    ) -> str:
        """Save champion model to disk for backend inference.

        Falls back to a local temp dir when the configured path
        (``/model_artifacts/champion``) is not writable — e.g. native macOS
        runs outside Docker. Uses atomic write (temp file + rename) so the
        backend never reads a partially-written model file. The checkpoint
        includes ticker vocabulary and standardisation params.

        Args:
            model: Trained GlobalLSTM instance.
            vocab: Ticker-to-index vocabulary for entity embedding lookup.
            feature_means: Per-feature means (from global pooled z-score).
            feature_stds: Per-feature stds (from global pooled z-score).

        Returns:
            Path to the saved model file.
        """
        save_dir = Path(ML_CONFIG.MODEL_ARTIFACT_DIR)
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):  # fmt: skip
            fallback = Path(tempfile.gettempdir()) / "stocklens_model"
            logger.warning(
                "Cannot write to %s, falling back to %s",
                save_dir,
                fallback,
            )
            save_dir = fallback
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

        # -- Publish to champion S3 bucket if configured --
        champion_s3_uri = os.environ.get("CHAMPION_S3_URI", "")
        if champion_s3_uri:
            s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
            # s3://bucket/prefix/ → bucket, prefix
            parts = champion_s3_uri.removeprefix("s3://").rstrip("/").split("/", 1)
            bucket = parts[0]
            key_prefix = f"{parts[1]}/" if len(parts) > 1 else ""

            # Publish loose model.pt (consumed by ECS bootstrap.py)
            s3_key = f"{key_prefix}model.pt"
            s3.upload_file(save_path, bucket, s3_key)
            logger.info("Champion model published to S3", extra={"bucket": bucket, "key": s3_key})

            # Also publish model.tar.gz (consumed by SageMaker model_data_url)
            import io  # noqa: E402  # ponytail: stdlib, no new dep
            import tarfile

            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
                tar.add(save_path, arcname="model.pt")
            tar_buffer.seek(0)
            tar_key = f"{key_prefix}model.tar.gz"
            s3.upload_fileobj(tar_buffer, bucket, tar_key)
            logger.info(
                "Champion model tar.gz published to S3", extra={"bucket": bucket, "key": tar_key}
            )

        return save_path
