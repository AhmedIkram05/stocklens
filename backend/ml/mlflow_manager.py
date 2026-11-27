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

import hashlib
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

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

    def log_metrics(
        self,
        metrics: dict[str, float],
        step: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Log metrics to a run (active, or *run_id* after it ended).

        Args:
            metrics: Dict of metric name to value.
            step: Optional step (epoch) number.
            run_id: Optional run to attach to; defaults to the active run.
        """
        kwargs: dict[str, Any] = {"step": step}
        if run_id is not None:
            kwargs["run_id"] = run_id
        mlflow.log_metrics(metrics, **kwargs)

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
        digest = hashlib.sha256(data.ravel()[:10_000].tobytes()).hexdigest()
        dataset = mlflow.data.from_numpy(data, name=name, digest=digest)
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

        info = mlflow.pytorch.log_model(
            pytorch_model=model,
            name=artifact_path,
            registered_model_name=registered_model_name,
            serialization_format="pickle",
            signature=signature,
        )

        version = self._registered_version(info, registered_model_name)
        run_id = self.active_run.info.run_id if self.active_run else "unknown"
        return run_id, version

    @staticmethod
    def _registered_version(info: Any, registered_model_name: str) -> str:
        """Prefer the version the registration call returned; max(version) is racy."""
        version = getattr(info, "registered_model_version", None)
        if version is None:
            client = mlflow.tracking.MlflowClient()
            versions = client.search_model_versions(f"name='{registered_model_name}'")
            version = str(max(int(v.version) for v in versions)) if versions else "1"
        return str(version)

    def log_ensemble_model(
        self,
        seed_models: list[GlobalLSTM],
        vocab: dict[str, int],
        feature_means: np.ndarray,
        feature_stds: np.ndarray,
        margin: float,
        registered_model_name: str = "GlobalLSTM",
        artifact_path: str = "ensemble",
    ) -> tuple[str, str]:
        """Register every seed member as one PyFunc version.

        Serving averages the five seeds; registering only the seed-0 reference
        made the registry champion a different model. The PyFunc loads all
        members from its artifacts and averages their softmax output.
        """
        from ml.ensemble_model import GlobalLSTMEnsemble

        if not seed_models:
            raise ValueError("log_ensemble_model requires at least one seed model")
        with tempfile.TemporaryDirectory() as tmp:
            members_dir = Path(tmp) / "members"
            members_dir.mkdir()
            for i, member in enumerate(seed_models):
                member.save(
                    str(members_dir / f"model_seed{i}.pt"),
                    vocab=vocab,
                    feature_means=feature_means,
                    feature_stds=feature_stds,
                    margin=margin,
                    ensemble_size=len(seed_models),
                )
            code_dir = Path(__file__).resolve().parent
            info = mlflow.pyfunc.log_model(
                name=artifact_path,
                python_model=GlobalLSTMEnsemble(member_count=len(seed_models)),
                artifacts={"members": str(members_dir)},
                registered_model_name=registered_model_name,
                code_paths=[str(code_dir / "ensemble_model.py"), str(code_dir / "model.py")],
            )
        version = self._registered_version(info, registered_model_name)
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

    async def read_champion_metrics(self) -> dict[str, Any] | None:
        """Read champion metrics from the model_registry DB table.

        Returns the raw ``test_metrics`` dict (with ``directional_accuracy``),
        or ``None`` if no champion exists.
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

    def _base_save_dir(self) -> Path:
        """Writable root for champion artifacts (``/model_artifacts/champion``).

        Falls back to a local temp dir when the configured path is not
        writable — e.g. native macOS runs outside Docker.
        """
        save_dir = Path(ML_CONFIG.MODEL_ARTIFACT_DIR)
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            probe = save_dir / ".write_test"
            probe.touch()
            probe.unlink()
        except (OSError, PermissionError):  # fmt: skip
            fallback = Path(tempfile.gettempdir()) / "stocklens_model"
            logger.warning(
                "Cannot write to %s, falling back to %s",
                save_dir,
                fallback,
            )
            save_dir = fallback
            save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir

    def _resolve_save_dir(self) -> Path:
        """Read the champion version currently referenced by the ``current`` file."""
        base = self._base_save_dir()
        pointer = base / "current"
        if pointer.is_file():
            candidate = base / "versions" / pointer.read_text().strip()
            if candidate.is_dir():
                return candidate
        return base

    def _atomic_save_model(
        self,
        model: GlobalLSTM,
        save_path: Path,
        *,
        vocab: Optional[dict[str, int]],
        feature_means: Optional[np.ndarray],
        feature_stds: Optional[np.ndarray],
        margin: Optional[float],
        ensemble_size: Optional[int] = None,
    ) -> None:
        """Write one checkpoint via a same-directory temp file + ``os.replace``.

        Atomic on POSIX (near-atomic on macOS), so a concurrent reader — the
        backend startup or the paired promotion gate — never observes a
        partially-written file.
        """
        fd, tmp_path = tempfile.mkstemp(dir=str(save_path.parent), suffix=".pt.tmp")
        try:
            model.save(
                tmp_path,
                vocab=vocab,
                feature_means=feature_means,
                feature_stds=feature_stds,
                margin=margin,
                ensemble_size=ensemble_size,
            )
            os.fsync(fd)  # flush OS buffer
            os.replace(tmp_path, str(save_path))  # atomic on POSIX, near-atomic on macOS
        finally:
            os.close(fd)
            # Clean up temp file if rename failed
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def save_champion_to_disk(
        self,
        model: GlobalLSTM,
        vocab: Optional[dict[str, int]] = None,
        feature_means: Optional[np.ndarray] = None,
        feature_stds: Optional[np.ndarray] = None,
        margin: Optional[float] = None,
        ensemble_models: Optional[list[GlobalLSTM]] = None,
    ) -> str:
        """Save champion model to disk for backend inference.

        Falls back to a local temp dir when the configured path
        (``/model_artifacts/champion``) is not writable — e.g. native macOS
        runs outside Docker. Every checkpoint is written atomically (temp file
        + ``os.replace``) so the backend never reads a partially-written model
        file. The checkpoint includes ticker vocabulary, standardisation params
        and the abstention margin selected on the validation set.

        The promoted champion is an N-seed probability ensemble: ``model.pt``
        is the seed-0 reference member (carries the metadata) and every seed is
        written as a ``model_seed{i}.pt`` sibling in a new version directory.
        The expected member count is stamped on ``model.pt`` so serving can
        refuse a truncated ensemble. The ``current`` pointer is flipped only
        after every member is written, so readers never observe a mixed set;
        older versions are pruned after the flip.

        Args:
            model: Trained GlobalLSTM instance — the seed-0 reference member.
            vocab: Ticker-to-index vocabulary for entity embedding lookup.
            feature_means: Per-feature means (from global pooled z-score).
            feature_stds: Per-feature stds (from global pooled z-score).
            margin: Abstention margin (|p_up - p_down| below this ⇒ FLAT).
            ensemble_models: Every seed model of the probability ensemble,
                written alongside ``model.pt`` as ``model_seed{i}.pt``;
                inference averages their outputs.

        Returns:
            Path to the saved model file.
        """
        base_dir = self._base_save_dir()
        version = f"v{uuid4().hex}"
        save_dir = base_dir / "versions" / version
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(save_dir / "model.pt")

        members = ensemble_models or []
        self._atomic_save_model(
            model,
            save_dir / "model.pt",
            vocab=vocab,
            feature_means=feature_means,
            feature_stds=feature_stds,
            margin=margin,
            ensemble_size=len(members),
        )
        for i, member in enumerate(members):
            self._atomic_save_model(
                member,
                save_dir / f"model_seed{i}.pt",
                vocab=vocab,
                feature_means=feature_means,
                feature_stds=feature_stds,
                margin=margin,
                ensemble_size=len(members),
            )
        logger.info(
            "Champion version written",
            extra={"path": str(save_dir), "members": len(members) + 1},
        )

        # Flip the pointer only after every member is written; readers resolve
        # the version through this file, so they never see a mixed ensemble.
        pointer_tmp = base_dir / ".current.tmp"
        pointer_tmp.write_text(version)
        os.replace(pointer_tmp, base_dir / "current")
        for old in (base_dir / "versions").iterdir():
            if old.is_dir() and old.name != version:
                shutil.rmtree(old, ignore_errors=True)
        for legacy in base_dir.glob("model*.pt"):
            legacy.unlink()

        champion_s3_uri = os.environ.get("CHAMPION_S3_URI", "")
        if champion_s3_uri:
            s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
            parts = champion_s3_uri.removeprefix("s3://").rstrip("/").split("/", 1)
            bucket = parts[0]
            key_prefix = f"{parts[1]}/" if len(parts) > 1 else ""
            version_prefix = f"{key_prefix}versions/{version}/"
            champion_files = [Path(save_path), *sorted(save_dir.glob("model_seed*.pt"))]
            for path in champion_files:
                s3_key = f"{version_prefix}{path.name}"
                s3.upload_file(str(path), bucket, s3_key)
                logger.info(
                    "Champion artifact published to S3",
                    extra={"bucket": bucket, "key": s3_key},
                )

            import io  # noqa: E402
            import tarfile

            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
                for path in champion_files:
                    tar.add(str(path), arcname=path.name)
            tar_buffer.seek(0)
            s3.upload_fileobj(tar_buffer, bucket, f"{key_prefix}model.tar.gz")
            # Pointer last: a reader that follows it sees the complete version.
            s3.put_object(Bucket=bucket, Key=f"{key_prefix}current", Body=version.encode())
            logger.info(
                "Champion version published and pointed",
                extra={"bucket": bucket, "prefix": version_prefix},
            )

        return save_path
