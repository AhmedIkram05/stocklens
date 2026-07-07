"""
Training pipeline orchestrator — GlobalLSTM directional forecasting.

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
    9. Log everything to MLflow, register champion
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
import torch
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.dataset import SequenceDataset, chronological_split, create_sliding_windows
from ml.evaluate import evaluate, plot_confusion_matrix, plot_loss_curves
from ml.features import compute_all_features, compute_cross_sectional_features
from ml.labeling import compute_adaptive_labels
from ml.mlflow_manager import MLflowManager
from ml.model import GlobalLSTM
from ml.train import train
from ml.utils import build_ticker_vocabulary, get_device, set_seed

logger = logging.getLogger(__name__)

# Configure logging at module level so INFO messages appear from the start.
# force=True ensures submodule imports that set up handlers don't silence us.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)


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
        # Single batch query with WHERE ticker = ANY($1)
        query = """
            SELECT ticker, date, open, high, low, close, adjusted_close, volume
            FROM ohlcv_prices
            WHERE ticker = ANY($1) AND date >= $2
            ORDER BY ticker, date ASC
        """
        rows = await conn.fetch(query, tickers, start_date)
        logger.info("Fetched %d rows for %d tickers", len(rows), len(tickers))

        # Group by ticker
        from collections import defaultdict

        by_ticker = defaultdict(list)
        for r in rows:
            by_ticker[r["ticker"]].append(r)

        result: dict[str, np.ndarray] = {}
        dtype = [
            ("date", "datetime64[D]"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("adjusted_close", "f8"),
            ("volume", "i8"),
        ]
        for ticker, ticker_rows in by_ticker.items():
            if len(ticker_rows) < ML_CONFIG.MIN_OHLCV_DAYS:
                logger.warning("Skipping %s: only %d days of data", ticker, len(ticker_rows))
                continue
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
                    for r in ticker_rows
                ],
                dtype=dtype,
            )
            result[ticker] = arr

    finally:
        await conn.close()

    logger.info("Fetched OHLCV data for %d tickers", len(result))
    return result


def prepare_global_dataset(
    ohlcv_data: dict[str, np.ndarray],
    vocab: dict[str, int],
    spy_features_df: pd.DataFrame | None = None,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Prepare unnormalized global dataset from per-ticker OHLCV data.

    **Does NOT normalize** — that happens AFTER the chronological split
    (``fit_normalize_splits``) so training stats don't leak into val/test.
    This is Issue 3 fix: previously z-score means/stds were fit on ALL data
    including the test portion.

    Adds a **vol percentile** feature — the percentile of each day's 30-day
    rolling vol within the ticker's own history (ticker-specific vol regime).

    When ``spy_features_df`` is provided, also adds **cross-sectional features**
    (excess_ret_1d/5d/21d) — each feature is the ticker's log return minus
    SPY's log return for the same window. This tells the model whether the
    stock outperformed/underperformed the market, a signal lost when per-ticker
    features are z-scored separately.

    Applies a **volatility regime filter** — discards windows where the
    ticker's rolling vol is below the configured percentile of its own history.
    Low-vol periods produce labels that are mostly noise (tiny moves
    classified as directional).

    Sequences are sorted by date globally across all tickers before returning,
    so the chronological split reflects real temporal ordering.

    For each ticker:
        1. Compute features (13 V1 technical indicators)
        2. Compute vol_pct (per-ticker vol regime context)
        3. Compute cross-sectional features (excess returns vs SPY, if available)
        4. Compute labels (adaptive UP/FLAT/DOWN with threshold_mult=0.7)
        5. Create sliding windows without normalization
        6. Filter out low-volatility windows

    Args:
        ohlcv_data: Dict mapping ticker -> OHLCV structured array.
        vocab: Ticker-to-index vocabulary.
        spy_features_df: Pre-computed SPY features with date index, or None.
            When None, only 14 features (13 V1 + vol_pct) are produced.
            When provided, 17 features (13 V1 + vol_pct + 3 excess returns).

    Returns:
        ``(global_sequences, global_labels, global_ticker_idxs)``
        All arrays are unnormalized. Normalize via ``fit_normalize_splits``
        after calling ``chronological_split``.
        Returns empty arrays if no data passes filtering.
    """
    all_sequences: list[np.ndarray] = []
    all_labels_list: list[np.ndarray] = []
    all_ticker_idxs: list[np.ndarray] = []
    all_dates_list: list[np.ndarray] = []

    for ticker, arr in ohlcv_data.items():
        df = pd.DataFrame(
            {
                "adjusted_close": arr["adjusted_close"],
                "high": arr["high"],
                "low": arr["low"],
                "volume": arr["volume"],
                "ticker": ticker,
            }
        )

        # 1. Compute 13 V1 technical indicators
        features_df = compute_all_features(df)
        named_features = features_df.drop(columns=["ticker"], errors="ignore")
        feature_values = named_features.values.astype(np.float32)  # (T, 13)

        # 2. Compute vol percentile feature (column 14)
        close_series = pd.Series(arr["adjusted_close"])
        daily_log_ret = np.log(close_series / close_series.shift(1))
        rolling_vol = daily_log_ret.rolling(window=ML_CONFIG.VOL_LOOKBACK).std()
        vol_pct = rolling_vol.rank(pct=True).values.astype(np.float32)[:, np.newaxis]
        # NaN from first VOL_LOOKBACK days → fill with 0.5 (50th percentile)
        vol_pct = np.nan_to_num(vol_pct, nan=0.5)

        # 3. Cross-sectional features vs SPY (columns 15-17: excess_ret_1d/5d/21d)
        if spy_features_df is not None:
            ticker_dates = arr["date"]
            named_features.index = ticker_dates
            spy_aligned = spy_features_df.reindex(ticker_dates)
            excess = compute_cross_sectional_features(named_features, spy_aligned)
            excess_values = excess.values.astype(np.float32)
            excess_values = np.nan_to_num(excess_values, nan=0.0)
            feature_values = np.concatenate(
                [feature_values, vol_pct, excess_values], axis=-1
            )  # (T, 17)
        else:
            # Fall back to 14 features (13 V1 + vol_pct only)
            feature_values = np.concatenate([feature_values, vol_pct], axis=-1)  # (T, 14)

        # 4. Compute labels
        labels = compute_adaptive_labels(
            close_series,
            vol_lookback=ML_CONFIG.VOL_LOOKBACK,
            threshold_mult=ML_CONFIG.THRESHOLD_MULT,
            forecast_horizon=ML_CONFIG.FORECAST_HORIZON,
        )
        label_values = labels.values.astype(np.float64)

        # 4. Create sliding windows (NO normalization — raw features)
        ticker_idx = vocab.get(ticker, 0)
        dates = ohlcv_data[ticker]["date"]

        sequences, seq_labels, seq_ticker_idxs, seq_dates = create_sliding_windows(
            feature_values,
            label_values,
            np.full(len(label_values), ticker_idx),
            sequence_length=ML_CONFIG.SEQUENCE_LENGTH,
            dates=dates,
        )

        if len(sequences) == 0:
            continue

        # 5. Volatility regime filter — discard windows from low-vol periods
        #    where labels are mostly noise. The vol_pct at the window endpoint
        #    tells us whether this ticker was in a meaningful vol regime.
        vol_pct_aligned = vol_pct[ML_CONFIG.SEQUENCE_LENGTH - 1 :]
        valid_idx = np.arange(len(seq_labels))
        # seq_labels are already NaN-filtered by create_sliding_windows,
        # so vol_pct_aligned[valid_idx] matches the kept windows.
        # Apply vol filter:
        keep = vol_pct_aligned[valid_idx].flatten() >= ML_CONFIG.VOL_FILTER_PERCENTILE
        sequences = sequences[keep]
        seq_labels = seq_labels[keep]
        seq_ticker_idxs = seq_ticker_idxs[keep]
        seq_dates = seq_dates[keep]

        if len(sequences) > 0:
            all_sequences.append(sequences)
            all_labels_list.append(seq_labels)
            all_ticker_idxs.append(seq_ticker_idxs)
            all_dates_list.append(seq_dates)

    if not all_sequences:
        return (
            np.empty((0, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES)),
            np.empty((0,)),
            np.empty((0,)),
        )

    global_sequences = np.concatenate(all_sequences, axis=0)
    global_labels = np.concatenate(all_labels_list, axis=0)
    global_ticker_idxs = np.concatenate(all_ticker_idxs, axis=0)
    global_dates = np.concatenate(all_dates_list, axis=0)

    # Sort globally by date so chronological_split reflects real temporal ordering
    sort_idx = np.argsort(global_dates, kind="stable")
    global_sequences = global_sequences[sort_idx]
    global_labels = global_labels[sort_idx]
    global_ticker_idxs = global_ticker_idxs[sort_idx]

    return global_sequences, global_labels, global_ticker_idxs


def fit_normalize_splits(
    train: tuple[np.ndarray, np.ndarray, np.ndarray],
    val: tuple[np.ndarray, np.ndarray, np.ndarray],
    test: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    np.ndarray,
    np.ndarray,
]:
    """Fit z-score normalizer on training data only, transform all splits.

    This fixes the data leakage issue (Issue 3) where global means/stds were
    previously computed on ALL data including the test set. Now the normalizer
    is fit exclusively on training sequences, and those same params are applied
    to val and test.

    Args:
        train: (sequences, labels, ticker_idxs) tuple for training.
        val: (sequences, labels, ticker_idxs) tuple for validation.
        test: (sequences, labels, ticker_idxs) tuple for testing.

    Returns:
        ``(train, val, test, means, stds)`` where each split is normalized
        using the SAME means/stds derived from training data only.
    """
    train_seq, train_labels, train_idxs = train
    val_seq, val_labels, val_idxs = val
    test_seq, test_labels, test_idxs = test

    # Fit on training data: flatten all windows × time steps → per-feature stats
    train_flat = train_seq.reshape(-1, train_seq.shape[-1])
    means = np.nanmean(train_flat, axis=0)
    stds = np.nanstd(train_flat, axis=0)
    stds[stds == 0] = 1.0

    def _normalize(seq: np.ndarray) -> np.ndarray:
        seq = (seq - means) / stds
        return np.nan_to_num(seq, nan=0.0)

    train_norm = (_normalize(train_seq), train_labels, train_idxs)
    val_norm = (_normalize(val_seq), val_labels, val_idxs)
    test_norm = (_normalize(test_seq), test_labels, test_idxs)

    return train_norm, val_norm, test_norm, means, stds


async def _run_lstm_pipeline(
    train_data: tuple[np.ndarray, np.ndarray, np.ndarray],
    val_data: tuple[np.ndarray, np.ndarray, np.ndarray],
    test_data: tuple[np.ndarray, np.ndarray, np.ndarray],
    tickers_with_data: list[str],
    vocab_size: int,
    vocab: dict[str, int],
    global_means: np.ndarray,
    global_stds: np.ndarray,
    device: torch.device,
) -> dict[str, Any]:
    """Train LSTM, evaluate, log to MLflow, register champion."""
    # --- Datasets and DataLoaders ---
    train_ds = SequenceDataset(*train_data)
    val_ds = SequenceDataset(*val_data)
    test_ds = SequenceDataset(*test_data)

    train_loader = DataLoader(train_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)

    # --- Initialise LSTM ---
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
    logger.info("LSTM initialised", extra={"params": param_count})

    # --- MLflow run ---
    run_name = f"lstm_{len(tickers_with_data)}tickers_h{ML_CONFIG.FORECAST_HORIZON}"
    mlflow_mgr = MLflowManager()
    mlflow_mgr.enable_autologging()
    mlflow_mgr.enable_system_metrics()
    run_id = mlflow_mgr.start_run(run_name=run_name)

    try:
        # Log common params
        mlflow_mgr.log_params(
            {
                "n_features": ML_CONFIG.N_FEATURES,
                "vocab_size": vocab_size,
                "embed_dim": ML_CONFIG.EMBED_DIM,
                "hidden_dim": ML_CONFIG.HIDDEN_DIM,
                "n_layers": ML_CONFIG.N_LAYERS,
                "dropout": ML_CONFIG.DROPOUT,
                "sequence_length": ML_CONFIG.SEQUENCE_LENGTH,
                "forecast_horizon": ML_CONFIG.FORECAST_HORIZON,
                "batch_size": ML_CONFIG.BATCH_SIZE,
                "learning_rate": ML_CONFIG.LEARNING_RATE,
                "weight_decay": ML_CONFIG.WEIGHT_DECAY,
                "patience": ML_CONFIG.PATIENCE,
                "threshold_mult": ML_CONFIG.THRESHOLD_MULT,
                "n_tickers": len(tickers_with_data),
                "model_type": "GlobalLSTM",
                "train_samples": len(train_ds),
                "val_samples": len(val_ds),
                "test_samples": len(test_ds),
            }
        )

        model_description = (
            "GlobalLSTM entity-embedding model trained on {ticker_count} S&P 500 "
            "stocks with {window}d windows and {n_features} technical indicators. "
            "Predicts UP/FLAT/DOWN at {horizon}d horizon."
        ).format(
            ticker_count=len(tickers_with_data),
            window=ML_CONFIG.SEQUENCE_LENGTH,
            n_features=ML_CONFIG.N_FEATURES,
            horizon=ML_CONFIG.FORECAST_HORIZON,
        )
        mlflow_mgr.set_run_description(
            f"GlobalLSTM h={ML_CONFIG.FORECAST_HORIZON} | "
            f"{len(tickers_with_data)} tickers | "
            f"{ML_CONFIG.SEQUENCE_LENGTH}d windows, {ML_CONFIG.N_FEATURES} features"
        )

        # Dataset tracking
        mlflow_mgr.log_dataset(train_data[0], name="train_features", context="train")
        mlflow_mgr.log_dataset(train_data[1], name="train_labels", context="train")
        mlflow_mgr.log_dataset(val_data[0], name="val_features", context="val")
        mlflow_mgr.log_dataset(val_data[1], name="val_labels", context="val")
        mlflow_mgr.log_dataset(test_data[0], name="test_features", context="test")
        mlflow_mgr.log_dataset(test_data[1], name="test_labels", context="test")

        # --- Train LSTM ---
        logger.info("Training LSTM")
        history = train(model, train_loader, val_loader, device=device, n_epochs=ML_CONFIG.EPOCHS)

        # Log epoch-level metrics — includes val_directional_accuracy for
        # early-stopping signal (the primary metric for noisy financial data)
        for epoch in range(len(history["train_losses"])):
            epoch_metrics = {
                "train_loss": history["train_losses"][epoch],
                "val_loss": history["val_losses"][epoch],
                "val_accuracy": history["val_accuracies"][epoch],
                "learning_rate": history["learning_rates"][epoch],
            }
            if "val_directional_accuracies" in history and epoch < len(
                history["val_directional_accuracies"]
            ):
                epoch_metrics["val_directional_accuracy"] = history["val_directional_accuracies"][
                    epoch
                ]
            mlflow_mgr.log_metrics(epoch_metrics, step=epoch + 1)

        # --- Evaluate ---
        test_metrics = evaluate(model, test_loader, device)
        logger.info("Test metrics: %s", test_metrics)

        mlflow_mgr.log_metrics(
            {
                "test_accuracy": test_metrics["accuracy"],
                "test_directional_accuracy": test_metrics["directional_accuracy"],
                "test_simulated_sharpe": test_metrics["simulated_sharpe"],
                "test_long_short_sharpe": test_metrics["long_short_sharpe"],
            }
        )
        for class_name, f1 in test_metrics["per_class_f1"].items():
            mlflow_mgr.log_metrics({f"f1_{class_name.lower()}": f1})

        # Plot and log artifacts
        cm_path = plot_confusion_matrix(np.array(test_metrics["confusion_matrix"]))
        mlflow_mgr.log_artifact(cm_path, artifact_path="evaluation")
        loss_path = plot_loss_curves(history["train_losses"], history["val_losses"])
        mlflow_mgr.log_artifact(loss_path, artifact_path="training")

        # --- Register champion ---
        lstm_version = mlflow_mgr.log_model(
            model,
            registered_model_name="GlobalLSTM",
        )[1]

        mlflow_mgr.set_model_description("GlobalLSTM", model_description)
        # ponytail: tags fixed — previously read "conv1d_bilstm_attention_
        # regimegate_v2" (V2 arch that was abandoned). Now accurate: V1 LSTM
        # with focal loss + per-ticker vol context + vol regime filter.
        mlflow_mgr.set_registered_model_tags(
            {
                "problem_type": "classification",
                "model_type": "GlobalLSTM_V1",
                "classes": "DOWN,FLAT,UP",
                "forecast_horizon": str(ML_CONFIG.FORECAST_HORIZON),
                "features": f"{ML_CONFIG.N_FEATURES}_features_incl_vol_pct_cross_sectional",
                "window_size": str(ML_CONFIG.SEQUENCE_LENGTH),
                "framework": "pytorch",
                "threshold_mult": str(ML_CONFIG.THRESHOLD_MULT),
                "loss": "focal_loss",
                "vol_filter_percentile": str(ML_CONFIG.VOL_FILTER_PERCENTILE),
            }
        )
        mlflow_mgr.set_experiment_tags(
            {
                "project": "stocklens",
                "model_type": "GlobalLSTM",
                "problem_type": "directional_price_prediction",
                "data_source": "yahoo_finance_ohlcv",
            }
        )

        # Only promote to champion if this run is the best so far
        is_best_run = mlflow_mgr.tag_best_run(metric="test_directional_accuracy")
        if is_best_run:
            mlflow_mgr.set_champion_alias(version=lstm_version)
            champion_path = mlflow_mgr.save_champion_to_disk(
                model,
                vocab=vocab,
                feature_means=global_means,
                feature_stds=global_stds,
            )
            await _record_in_db(run_id, lstm_version, test_metrics)
        else:
            champion_path = None
            logger.info(
                "Champion unchanged — run did not beat best on %s", "test_directional_accuracy"
            )

    finally:
        mlflow_mgr.end_run()

    logger.info(
        "Pipeline complete",
        extra={"champion_path": champion_path, "run_id": run_id},
    )
    return test_metrics


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

    # 3. Fetch SPY benchmark and compute its features for cross-sectional context
    spy_features_df = None
    try:
        spy_ohlcv = await fetch_ohlcv_for_tickers([ML_CONFIG.BENCHMARK_TICKER])
        if ML_CONFIG.BENCHMARK_TICKER in spy_ohlcv:
            spy_arr = spy_ohlcv[ML_CONFIG.BENCHMARK_TICKER]
            spy_df = pd.DataFrame(
                {
                    "adjusted_close": spy_arr["adjusted_close"],
                    "high": spy_arr["high"],
                    "low": spy_arr["low"],
                    "volume": spy_arr["volume"],
                }
            )
            spy_features = compute_all_features(spy_df)
            spy_features_df = spy_features.drop(columns=["ticker"], errors="ignore")
            spy_features_df.index = spy_arr["date"]
            logger.info("SPY benchmark features computed for cross-sectional context")
        else:
            logger.warning("SPY not in OHLCV data — training with 14 features (no cross-sectional)")
    except Exception:
        logger.warning("Failed to compute SPY features — training with 14 features", exc_info=True)

    # 5. Prepare global dataset (unnormalized — normalization happens after split)
    global_sequences, global_labels, global_ticker_idxs = prepare_global_dataset(
        ohlcv_data,
        vocab,
        spy_features_df=spy_features_df,
    )
    logger.info("Global dataset prepared", extra={"samples": len(global_sequences)})

    if len(global_sequences) < 100:
        logger.error("Too few samples (%d) - aborting", len(global_sequences))
        return {"error": 1.0}

    # 6. Chronological split (UNNORMALIZED — preserves temporal ordering)
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

    # 7. Normalize using TRAINING stats only (fixes data leak — Issue 3)
    train_data, val_data, test_data, global_means, global_stds = fit_normalize_splits(
        train_data,
        val_data,
        test_data,
    )
    logger.info("Normalization complete — means/stds fit on training data only")

    # 8. Train LSTM, evaluate, register
    test_metrics = await _run_lstm_pipeline(
        train_data,
        val_data,
        test_data,
        tickers_with_data,
        vocab_size,
        vocab,
        global_means,
        global_stds,
        device,
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
