"""
Training pipeline orchestrator.

Run via: docker compose run ml python -m ml.pipeline

Flow:
    1. Fetch OHLCV for training tickers from PostgreSQL
    2. Compute features and labels per ticker
    3. Build ticker vocabulary
    4. Merge into global dataset with chronological ordering
    5. Train/val/test split (chronological 70/15/15)
    6. Create DataLoaders
    7. Train GlobalLSTM
    8. Evaluate on test set
    9. Log everything to MLflow
    10. Register champion, save to disk, record in model_registry DB
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.dataset import SequenceDataset, chronological_split, create_sliding_windows
from ml.evaluate import evaluate, plot_confusion_matrix, plot_loss_curves
from ml.features import compute_all_features
from ml.labeling import compute_adaptive_labels
from ml.mlflow_manager import MLflowManager
from ml.model import GlobalLSTM
from ml.train import train
from ml.utils import build_ticker_vocabulary, get_device, set_seed

logger = logging.getLogger(__name__)


async def fetch_ohlcv_for_tickers(tickers: list[str]) -> dict[str, np.ndarray]:
    """Fetch OHLCV data from PostgreSQL for all training tickers.

    Each ticker's data is returned as a structured numpy array with columns:
        date, open, high, low, close, adjusted_close, volume

    Args:
        tickers: List of ticker symbols.

    Returns:
        Dict mapping ticker -> numpy structured array.
    """
    import asyncpg

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    start_date = date.today() - timedelta(days=int(ML_CONFIG.OHLCV_YEARS * 365.25))

    def _to_float(v):
        """Convert DB Decimal or None to float, using NaN for NULL."""
        return float(v) if v is not None else float("nan")

    conn = await asyncpg.connect(dsn)
    try:
        result: dict[str, np.ndarray] = {}
        for ticker in tickers:
            rows = await conn.fetch(
                """
                SELECT date, open, high, low, close, adjusted_close, volume
                FROM ohlcv_prices
                WHERE ticker = $1 AND date >= $2
                ORDER BY date ASC
                """,
                ticker,
                start_date,
            )
            if len(rows) < ML_CONFIG.MIN_OHLCV_DAYS:
                logger.warning("Skipping %s: only %d days of data", ticker, len(rows))
                continue

            # Convert to numpy structured array
            dtype = [
                ("date", "datetime64[D]"),
                ("open", "f8"),
                ("high", "f8"),
                ("low", "f8"),
                ("close", "f8"),
                ("adjusted_close", "f8"),
                ("volume", "i8"),
            ]
            arr = np.array(
                [
                    (
                        r["date"],
                        _to_float(r["open"]),
                        _to_float(r["high"]),
                        _to_float(r["low"]),
                        _to_float(r["close"]),
                        _to_float(r["adjusted_close"]),
                        int(r["volume"] or 0),
                    )
                    for r in rows
                ],
                dtype=dtype,
            )
            if len(arr) >= ML_CONFIG.MIN_OHLCV_DAYS:
                result[ticker] = arr

    finally:
        await conn.close()

    logger.info("Fetched OHLCV data", extra={"tickers": len(result)})
    return result


def prepare_global_dataset(
    ohlcv_data: dict[str, np.ndarray],
    vocab: dict[str, int],
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Prepare global dataset from per-ticker OHLCV data.

    Uses **global pooled** z-score standardisation (one set of means/stds
    across all tickers) so inference applies the same transform.

    For each ticker:
        1. Compute features (technical indicators)
        2. Compute labels (adaptive UP/FLAT/DOWN)
        3. Pool raw features for global mean/std computation
        4. Second pass: standardise using global params, create windows
        5. Assign ticker index

    Args:
        ohlcv_data: Dict mapping ticker -> OHLCV structured array.
        vocab: Ticker-to-index vocabulary.

    Returns:
        ``(global_sequences, global_labels, global_ticker_idxs,
          global_means, global_stds)``
        Returns empty arrays if no data passes filtering.
    """
    all_sequences: list[np.ndarray] = []
    all_labels_list: list[np.ndarray] = []
    all_ticker_idxs: list[np.ndarray] = []

    # First pass: compute features and labels, collect raw values for pooling
    ticker_features: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    raw_feature_arrays: list[np.ndarray] = []

    for ticker, arr in ohlcv_data.items():
        df = pd.DataFrame(
            {
                "adjusted_close": arr["adjusted_close"],
                "ticker": ticker,
            }
        )

        features_df = compute_all_features(df)

        close_series = pd.Series(arr["adjusted_close"])
        labels = compute_adaptive_labels(
            close_series,
            vol_lookback=ML_CONFIG.VOL_LOOKBACK,
            threshold_mult=ML_CONFIG.THRESHOLD_MULT,
        )

        feature_values = features_df.drop(columns=["ticker"], errors="ignore").values.astype(
            np.float32
        )
        label_values = labels.values.astype(np.float64)

        ticker_features[ticker] = (feature_values, label_values)
        raw_feature_arrays.append(feature_values)

    if not ticker_features:
        empty = (
            np.empty((0, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES)),
            np.empty((0,)),
            np.empty((0,)),
        )
        return (*empty, np.zeros(ML_CONFIG.N_FEATURES), np.ones(ML_CONFIG.N_FEATURES))

    # Global pooled standardisation
    all_raw = np.concatenate(raw_feature_arrays, axis=0)
    global_means = np.nanmean(all_raw, axis=0)
    global_stds = np.nanstd(all_raw, axis=0)
    global_stds[global_stds == 0] = 1.0

    # Second pass: standardise using global params, create windows
    for ticker, (feature_values, label_values) in ticker_features.items():
        ticker_idx = vocab.get(ticker, 0)

        feature_values = (feature_values - global_means) / global_stds
        feature_values = np.nan_to_num(feature_values, nan=0.0)

        sequences, seq_labels, seq_ticker_idxs = create_sliding_windows(
            feature_values,
            label_values,
            np.full(len(label_values), ticker_idx),
            sequence_length=ML_CONFIG.SEQUENCE_LENGTH,
        )

        if len(sequences) > 0:
            all_sequences.append(sequences)
            all_labels_list.append(seq_labels)
            all_ticker_idxs.append(seq_ticker_idxs)

    if not all_sequences:
        return (
            np.empty((0, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES)),
            np.empty((0,)),
            np.empty((0,)),
            global_means,
            global_stds,
        )

    global_sequences = np.concatenate(all_sequences, axis=0)
    global_labels = np.concatenate(all_labels_list, axis=0)
    global_ticker_idxs = np.concatenate(all_ticker_idxs, axis=0)

    return global_sequences, global_labels, global_ticker_idxs, global_means, global_stds


async def run_pipeline() -> dict[str, Any]:
    """Run the full training pipeline.

    Returns:
        Dict of test set metrics.
    """
    set_seed(42)
    device = get_device()
    logger.info("Starting ML pipeline", extra={"device": str(device)})

    # 1. Fetch OHLCV data
    logger.info("Fetching OHLCV data for %d tickers", len(ML_CONFIG.TRAINING_TICKERS))
    ohlcv_data = await fetch_ohlcv_for_tickers(ML_CONFIG.TRAINING_TICKERS)
    if not ohlcv_data:
        logger.error("No OHLCV data fetched - aborting")
        return {"error": 1.0}

    # 2. Build ticker vocabulary
    tickers_with_data = list(ohlcv_data.keys())
    vocab, vocab_size = build_ticker_vocabulary(tickers_with_data)
    logger.info(
        "Ticker vocabulary built",
        extra={"vocab_size": vocab_size, "tickers": len(tickers_with_data)},
    )

    # 3. Prepare global dataset
    global_sequences, global_labels, global_ticker_idxs, global_means, global_stds = (
        prepare_global_dataset(ohlcv_data, vocab)
    )
    logger.info("Global dataset prepared", extra={"samples": len(global_sequences)})

    if len(global_sequences) < 100:
        logger.error("Too few samples (%d) - aborting", len(global_sequences))
        return {"error": 1.0}

    # 4. Chronological split
    train_data, val_data, test_data = chronological_split(
        global_sequences,
        global_labels,
        global_ticker_idxs,
        train_frac=ML_CONFIG.TRAIN_SPLIT,
        val_frac=ML_CONFIG.VAL_SPLIT,
    )
    logger.info(
        "Dataset split - train: %d, val: %d, test: %d",
        len(train_data[0]),
        len(val_data[0]),
        len(test_data[0]),
    )

    # 5. Create DataLoaders
    train_ds = SequenceDataset(*train_data)
    val_ds = SequenceDataset(*val_data)
    test_ds = SequenceDataset(*test_data)

    # ponytail: num_workers=0 for CPU training. Set >0 for GPU with appropriate
    # multiprocessing context.
    train_loader = DataLoader(train_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
    val_loader = DataLoader(val_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)

    # 6. Initialise model
    model = GlobalLSTM(
        n_features=ML_CONFIG.N_FEATURES,
        vocab_size=vocab_size,
        embed_dim=ML_CONFIG.EMBED_DIM,
        hidden_dim=ML_CONFIG.HIDDEN_DIM,
        n_layers=ML_CONFIG.N_LAYERS,
        dropout=ML_CONFIG.DROPOUT,
        n_classes=ML_CONFIG.N_CLASSES,
    )
    param_count = sum(p.numel() for p in model.parameters())
    logger.info("Model initialised", extra={"params": param_count})

    # 7. Start MLflow run
    mlflow_mgr = MLflowManager()
    run_id = mlflow_mgr.start_run(run_name=f"global_lstm_v1_{len(tickers_with_data)}tickers")

    try:
        # Log config params
        mlflow_mgr.log_params(
            {
                "n_features": ML_CONFIG.N_FEATURES,
                "vocab_size": vocab_size,
                "embed_dim": ML_CONFIG.EMBED_DIM,
                "hidden_dim": ML_CONFIG.HIDDEN_DIM,
                "n_layers": ML_CONFIG.N_LAYERS,
                "dropout": ML_CONFIG.DROPOUT,
                "sequence_length": ML_CONFIG.SEQUENCE_LENGTH,
                "batch_size": ML_CONFIG.BATCH_SIZE,
                "learning_rate": ML_CONFIG.LEARNING_RATE,
                "weight_decay": ML_CONFIG.WEIGHT_DECAY,
                "patience": ML_CONFIG.PATIENCE,
                "n_tickers": len(tickers_with_data),
                "train_samples": len(train_ds),
                "val_samples": len(val_ds),
                "test_samples": len(test_ds),
            }
        )

        # 8. Train
        history = train(
            model,
            train_loader,
            val_loader,
            device=device,
            n_epochs=ML_CONFIG.EPOCHS,
        )

        # Log epoch-level metrics
        for epoch in range(len(history["train_losses"])):
            mlflow_mgr.log_metrics(
                {
                    "train_loss": history["train_losses"][epoch],
                    "val_loss": history["val_losses"][epoch],
                    "val_accuracy": history["val_accuracies"][epoch],
                },
                step=epoch + 1,
            )

        # 9. Evaluate on test set
        test_metrics = evaluate(model, test_loader, device)
        logger.info("Test metrics: %s", test_metrics)

        # Log test metrics
        mlflow_mgr.log_metrics(
            {
                "test_accuracy": test_metrics["accuracy"],
                "test_directional_accuracy": test_metrics["directional_accuracy"],
                "test_simulated_sharpe": test_metrics["simulated_sharpe"],
            }
        )

        for class_name, f1 in test_metrics["per_class_f1"].items():
            mlflow_mgr.log_metrics({f"f1_{class_name.lower()}": f1})

        # 10. Plot and log artifacts
        cm_path = plot_confusion_matrix(np.array(test_metrics["confusion_matrix"]))
        mlflow_mgr.log_artifact(cm_path, artifact_path="evaluation")

        loss_path = plot_loss_curves(history["train_losses"], history["val_losses"])
        mlflow_mgr.log_artifact(loss_path, artifact_path="training")

        # 11. Log model and register
        _, model_version = mlflow_mgr.log_model(model)
        mlflow_mgr.set_champion_alias(version=model_version)

        # 12. Save champion to shared volume for backend inference
        champion_path = mlflow_mgr.save_champion_to_disk(
            model,
            vocab=vocab,
            feature_means=global_means,
            feature_stds=global_stds,
        )

        # 13. Record in model_registry DB
        await _record_in_db(run_id, model_version, test_metrics)

    finally:
        mlflow_mgr.end_run()

    logger.info(
        "Pipeline complete",
        extra={"champion_path": champion_path, "run_id": run_id},
    )
    return test_metrics


async def _record_in_db(
    run_id: str,
    model_version: str,
    metrics: dict,
) -> None:
    """Record the champion model in the model_registry DB table."""
    import asyncpg

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            # Remove existing champion for this model type
            await conn.execute(
                "UPDATE model_registry SET alias = NULL WHERE alias = 'champion'",
            )
            # Insert new champion
            await conn.execute(
                """
                INSERT INTO model_registry (ticker, mlflow_run_id, model_version, alias, metrics)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                None,  # Global model - no specific ticker
                run_id,
                model_version,
                "champion",
                json.dumps(metrics),
            )
    finally:
        await conn.close()
    logger.info("Champion recorded in model_registry", extra={"run_id": run_id})


def main() -> None:
    """Entry point for the training pipeline.

    Usage: docker compose run ml python -m ml.pipeline
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    metrics = asyncio.run(run_pipeline())

    if "error" in metrics:
        sys.exit(1)

    print("\n=== Training Complete ===")
    print(f"Test Directional Accuracy: {metrics.get('directional_accuracy', 0):.2%}")
    print(f"Test Simulated Sharpe: {metrics.get('simulated_sharpe', 0):.2f}")
    print(f"Per-class F1: {metrics.get('per_class_f1', {})}")
    sys.exit(0)


if __name__ == "__main__":
    main()
