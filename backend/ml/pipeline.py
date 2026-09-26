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
import os
import sys
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.dataset import SequenceDataset, chronological_split, create_sliding_windows
from ml.evaluate import (
    apply_margin_rule,
    evaluate_from_probs,
    plot_confusion_matrix,
    plot_loss_curves,
    predict_probs,
    sweep_margin,
)
from ml.features import (
    compute_all_features,
    compute_causal_vol_pct,
    compute_cross_sectional_features,
)
from ml.labeling import compute_adaptive_labels, compute_forward_returns
from ml.mlflow_manager import MLflowManager
from ml.model import GlobalLSTM
from ml.promotion_stats import decide_promotion_paired, should_promote
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
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Prepare unnormalized global dataset from per-ticker OHLCV data.

    **Does NOT normalize** — that happens AFTER the chronological split
    (``fit_normalize_splits``) so training stats don't leak into val/test.

    Adds a **causal vol percentile** feature — the expanding-window percentile
    of each day's 30-day rolling vol within the ticker's own PRIOR history
    only (``compute_causal_vol_pct``). The previous full-history rank peeked
    at the future; the prediction service now uses the same causal
    computation so training and inference see identical distributions.

    When ``spy_features_df`` is provided, also adds **cross-sectional features**
    (excess_ret_1d/5d/21d) — each feature is the ticker's log return minus
    SPY's log return for the same window.

    Each window carries its **end date** and the **actual forward log return**
    realized after the window (real-return Sharpe evaluation — no
    label-magnitude proxies). The optional volatility regime filter is NOT
    applied here: when enabled (``ML_VOL_FILTER``) it is applied to the TRAIN
    split only, in ``run_pipeline``, after the chronological split, so val/test
    always reflect the unfiltered live distribution.

    Sequences are sorted by date globally across all tickers before returning,
    so the chronological split reflects real temporal ordering.

    Args:
        ohlcv_data: Dict mapping ticker -> OHLCV structured array.
        vocab: Ticker-to-index vocabulary.
        spy_features_df: Pre-computed SPY features with date index, or None.
            When None, only 14 features (13 V1 + vol_pct) are produced.
            When provided, 17 features (13 V1 + vol_pct + 3 excess returns).

    Returns:
        ``(global_sequences, global_labels, global_ticker_idxs, global_dates,
        global_fwd_rets)``. All arrays are unnormalized. Returns empty arrays
        if no data passes filtering.
    """
    # Drop tickers whose data ended long before the dataset's most recent
    # date — bulk snapshot ingest (e.g. Kaggle) includes thousands of
    # delisted names that contribute survivorship noise and can never
    # appear in the recent evaluation era.
    if ML_CONFIG.TICKER_MIN_RECENCY_DAYS > 0 and ohlcv_data:
        global_max = max(arr["date"].max() for arr in ohlcv_data.values())
        cutoff = global_max - np.timedelta64(ML_CONFIG.TICKER_MIN_RECENCY_DAYS, "D")
        kept = {t: arr for t, arr in ohlcv_data.items() if arr["date"].max() >= cutoff}
        logger.info(
            "Ticker recency filter: kept %d of %d tickers (data must reach %s)",
            len(kept),
            len(ohlcv_data),
            cutoff,
        )
        ohlcv_data = kept

    all_sequences: list[np.ndarray] = []
    all_labels_list: list[np.ndarray] = []
    all_ticker_idxs: list[np.ndarray] = []
    all_dates_list: list[np.ndarray] = []
    all_fwd_rets_list: list[np.ndarray] = []

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

        # 2. Causal vol percentile feature (column 14)
        close_series = pd.Series(arr["adjusted_close"])
        daily_log_ret = np.log(close_series / close_series.shift(1))
        rolling_vol = daily_log_ret.rolling(window=ML_CONFIG.VOL_LOOKBACK).std()
        vol_pct = compute_causal_vol_pct(
            rolling_vol, min_periods=ML_CONFIG.VOL_PCT_MIN_PERIODS
        ).values.astype(np.float32)[:, np.newaxis]
        # NaN head (before min_periods observations) → 0.5 (50th percentile)
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

        # 4. Labels + actual forward returns (real-return Sharpe evaluation)
        labels = compute_adaptive_labels(
            close_series,
            vol_lookback=ML_CONFIG.VOL_LOOKBACK,
            threshold_mult=ML_CONFIG.THRESHOLD_MULT,
            forecast_horizon=ML_CONFIG.FORECAST_HORIZON,
        )
        label_values = labels.values.astype(np.float64)
        fwd_ret_values = compute_forward_returns(
            close_series, ML_CONFIG.FORECAST_HORIZON
        ).values.astype(np.float64)

        # 5. Sliding windows (NO normalization — raw features)
        ticker_idx = vocab.get(ticker, 0)
        dates = ohlcv_data[ticker]["date"]

        sequences, seq_labels, seq_ticker_idxs, seq_dates, seq_fwd_rets = create_sliding_windows(
            feature_values,
            label_values,
            np.full(len(label_values), ticker_idx),
            sequence_length=ML_CONFIG.SEQUENCE_LENGTH,
            dates=dates,
            forward_returns=fwd_ret_values,
        )

        if len(sequences) == 0:
            continue

        all_sequences.append(sequences)
        all_labels_list.append(seq_labels)
        all_ticker_idxs.append(seq_ticker_idxs)
        all_dates_list.append(seq_dates)
        all_fwd_rets_list.append(seq_fwd_rets)

    if not all_sequences:
        return (
            np.empty((0, ML_CONFIG.SEQUENCE_LENGTH, ML_CONFIG.N_FEATURES)),
            np.empty((0,)),
            np.empty((0,)),
            np.empty((0,), dtype="datetime64[D]"),
            np.empty((0,)),
        )

    global_sequences = np.concatenate(all_sequences, axis=0)
    global_labels = np.concatenate(all_labels_list, axis=0)
    global_ticker_idxs = np.concatenate(all_ticker_idxs, axis=0)
    global_dates = np.concatenate(all_dates_list, axis=0)
    global_fwd_rets = np.concatenate(all_fwd_rets_list, axis=0)

    # Sort globally by date so chronological_split reflects real temporal ordering
    sort_idx = np.argsort(global_dates, kind="stable")
    global_sequences = global_sequences[sort_idx]
    global_labels = global_labels[sort_idx]
    global_ticker_idxs = global_ticker_idxs[sort_idx]
    global_dates = global_dates[sort_idx]
    global_fwd_rets = global_fwd_rets[sort_idx]

    return (
        global_sequences,
        global_labels,
        global_ticker_idxs,
        global_dates,
        global_fwd_rets,
    )


def fit_normalize_splits(
    train: tuple[np.ndarray, ...],
    val: tuple[np.ndarray, ...],
    test: tuple[np.ndarray, ...],
) -> tuple[
    tuple[np.ndarray, ...],
    tuple[np.ndarray, ...],
    tuple[np.ndarray, ...],
    np.ndarray,
    np.ndarray,
]:
    """Fit z-score normalizer on training data only, transform all splits.

    This fixes the data leakage issue (Issue 3) where global means/stds were
    previously computed on ALL data including the test set. Now the normalizer
    is fit exclusively on training sequences, and those same params are applied
    to val and test.

    Split tuples are ``(sequences, labels, ticker_idxs, ...)`` — any extra
    per-window metadata (dates, forward returns) is passed through untouched.

    Returns:
        ``(train, val, test, means, stds)`` where each split is normalized
        using the SAME means/stds derived from training data only.
    """
    train_seq, train_labels, train_idxs = train[0], train[1], train[2]
    val_seq, val_labels, val_idxs = val[0], val[1], val[2]
    test_seq, test_labels, test_idxs = test[0], test[1], test[2]

    # Fit on training data: flatten all windows × time steps → per-feature stats
    train_flat = train_seq.reshape(-1, train_seq.shape[-1])
    means = np.nanmean(train_flat, axis=0)
    stds = np.nanstd(train_flat, axis=0)
    stds[stds == 0] = 1.0

    def _normalize(seq: np.ndarray) -> np.ndarray:
        seq = (seq - means) / stds
        return np.nan_to_num(seq, nan=0.0)

    train_norm = (_normalize(train_seq), train_labels, train_idxs, *train[3:])
    val_norm = (_normalize(val_seq), val_labels, val_idxs, *val[3:])
    test_norm = (_normalize(test_seq), test_labels, test_idxs, *test[3:])

    return train_norm, val_norm, test_norm, means, stds


async def _run_lstm_pipeline(
    train_data: tuple[np.ndarray, ...],
    val_data: tuple[np.ndarray, ...],
    test_data: tuple[np.ndarray, ...],
    tickers_with_data: list[str],
    vocab_size: int,
    vocab: dict[str, int],
    global_means: np.ndarray,
    global_stds: np.ndarray,
    device: torch.device,
) -> tuple[dict[str, Any], str, GlobalLSTM, str, np.ndarray, list[GlobalLSTM]]:
    """Train LSTM (multi-seed), sweep abstention margin on val, evaluate test.

    Trains ``ML_CONFIG.N_SEEDS`` model(s) (different init/data-order seeds),
    selects the best by SMOOTHED validation directional accuracy (never by
    test), sweeps the abstention margin on validation for every seed, and
    evaluates each seed once on test. Across-seed mean/std of headline
    metrics are logged for honest variance reporting.

    Returns:
        ``(test_metrics, model_version, model, run_id, challenger_preds)``
        for the selected seed; ``challenger_preds`` are the selected seed's
        test-set class predictions under its margin rule (used by the paired
        promotion gate). Does NOT gate promotion — ``run_pipeline()`` does.
    """
    # --- Datasets and DataLoaders ---
    # Last two tuple slots are (dates, fwd_rets) — pass as keywords because
    # SequenceDataset's signature order is (forward_returns, dates).
    train_ds = SequenceDataset(
        train_data[0],
        train_data[1],
        train_data[2],
        dates=train_data[3],
        forward_returns=train_data[4],
    )
    val_ds = SequenceDataset(
        val_data[0],
        val_data[1],
        val_data[2],
        dates=val_data[3],
        forward_returns=val_data[4],
    )
    test_ds = SequenceDataset(
        test_data[0],
        test_data[1],
        test_data[2],
        dates=test_data[3],
        forward_returns=test_data[4],
    )

    train_loader = DataLoader(train_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)

    n_features = train_data[0].shape[-1]

    def _new_model() -> GlobalLSTM:
        return GlobalLSTM(
            n_features=n_features,
            vocab_size=vocab_size,
            embed_dim=ML_CONFIG.EMBED_DIM,
            hidden_dim=ML_CONFIG.HIDDEN_DIM,
            n_layers=ML_CONFIG.N_LAYERS,
            dropout=ML_CONFIG.DROPOUT,
            n_classes=ML_CONFIG.N_CLASSES,
        )

    param_count = sum(p.numel() for p in _new_model().parameters())
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
                "n_features": n_features,
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
                "n_seeds": ML_CONFIG.N_SEEDS,
                "embargo_days": ML_CONFIG.EMBARGO_DAYS,
                "vol_filter_percentile": ML_CONFIG.VOL_FILTER_PERCENTILE,
                "margin_sweep": (
                    f"{ML_CONFIG.MARGIN_MIN}-{ML_CONFIG.MARGIN_MAX} step {ML_CONFIG.MARGIN_STEP}"
                ),
                "cost_bps_round_trip": ML_CONFIG.COST_BPS_ROUND_TRIP,
            }
        )

        model_description = (
            "GlobalLSTM entity-embedding model trained on {ticker_count} US stocks "
            "with {window}d windows and {n_features} technical indicators. "
            "Predicts UP/FLAT/DOWN at {horizon}d horizon with an abstention "
            "margin tuned on validation data."
        ).format(
            ticker_count=len(tickers_with_data),
            window=ML_CONFIG.SEQUENCE_LENGTH,
            n_features=n_features,
            horizon=ML_CONFIG.FORECAST_HORIZON,
        )
        mlflow_mgr.set_run_description(
            f"GlobalLSTM h={ML_CONFIG.FORECAST_HORIZON} | "
            f"{len(tickers_with_data)} tickers | "
            f"{ML_CONFIG.SEQUENCE_LENGTH}d windows, {n_features} features"
        )

        # Dataset tracking
        mlflow_mgr.log_dataset(train_data[0], name="train_features", context="train")
        mlflow_mgr.log_dataset(train_data[1], name="train_labels", context="train")
        mlflow_mgr.log_dataset(val_data[0], name="val_features", context="val")
        mlflow_mgr.log_dataset(val_data[1], name="val_labels", context="val")
        mlflow_mgr.log_dataset(test_data[0], name="test_features", context="test")
        mlflow_mgr.log_dataset(test_data[1], name="test_labels", context="test")

        # --- Train one model per seed; select by smoothed VAL dir accuracy ---
        seed_results: list[dict[str, Any]] = []
        for seed_i in range(max(1, ML_CONFIG.N_SEEDS)):
            seed = 42 + seed_i
            set_seed(seed)
            seed_model = _new_model()
            logger.info("Training LSTM (seed %d, %d/%d)", seed, seed_i + 1, ML_CONFIG.N_SEEDS)
            history = train(
                seed_model, train_loader, val_loader, device=device, n_epochs=ML_CONFIG.EPOCHS
            )

            # Sweep the abstention margin on VALIDATION data (never test):
            # trade only when |P(UP)-P(DOWN)| >= margin, else predict FLAT.
            # Default OFF: argmax over val Sharpe across 17 margin candidates
            # is a winner's-curse lottery — empirically selects margins that
            # are anti-correlated on test. ML_MARGIN_SWEEP=1 re-enables.
            if ML_CONFIG.MARGIN_SWEEP_ENABLED:
                val_probs, val_labels_arr = predict_probs(seed_model, val_loader, device)
                margin, margin_curve = sweep_margin(
                    val_probs, val_labels_arr, val_data[4], val_data[3], val_data[2]
                )
            else:
                margin, margin_curve = 0.0, [{"margin": 0.0}]

            probs, labels_arr = predict_probs(seed_model, test_loader, device)
            test_metrics = evaluate_from_probs(
                probs,
                labels_arr,
                margin=margin,
                fwd_rets=test_data[4],
                dates=test_data[3],
                ticker_idxs=test_data[2],
            )
            seed_results.append(
                {
                    "seed": seed,
                    "model": seed_model,
                    "history": history,
                    "margin": margin,
                    "margin_curve": margin_curve,
                    "test_metrics": test_metrics,
                    "probs": probs,
                }
            )
            logger.info(
                "Seed %d — smoothed val dir acc %.4f, test dir acc %.4f, "
                "test 3-class acc %.4f, coverage %.0f%%, margin %.2f, "
                "ls Sharpe %.2f@0bps",
                seed,
                history["best_dir_acc"],
                test_metrics["directional_accuracy"],
                test_metrics["accuracy"],
                test_metrics["coverage"] * 100,
                margin,
                test_metrics["sharpe_long_short_0bps"] or 0.0,
            )

        # Challenger = probability ENSEMBLE over all seeds. Averaging removes
        # the seed lottery: picking one seed by val accuracy hit winner's
        # curse in every multi-seed run (highest val → lowest test).
        ens_probs = np.mean([r["probs"] for r in seed_results], axis=0)
        ens_margin = float(np.mean([r["margin"] for r in seed_results]))
        test_metrics = evaluate_from_probs(
            ens_probs,
            test_data[1],
            margin=ens_margin,
            fwd_rets=test_data[4],
            dates=test_data[3],
            ticker_idxs=test_data[2],
        )
        # Epoch metrics / registry artifact still come from the val-best seed.
        best = max(seed_results, key=lambda r: r["history"]["best_dir_acc"])
        model = seed_results[0]["model"]
        history = best["history"]
        logger.info(
            "Seed-ensemble (%d seeds) — test dir acc %.4f, coverage %.2f, margin %.2f",
            len(seed_results),
            test_metrics["directional_accuracy"],
            test_metrics["coverage"],
            ens_margin,
        )

        # Log epoch-level metrics from the selected seed — includes
        # val_directional_accuracy (the smoothed early-stopping signal)
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

        # --- Log test metrics (selected seed + across-seed aggregates) ---
        sharpe_keys = (
            "sharpe_long_only_0bps",
            "sharpe_long_only_10bps",
            "sharpe_long_short_0bps",
            "sharpe_long_short_10bps",
        )
        test_metrics_to_log: dict[str, float] = {
            "test_accuracy": test_metrics["accuracy"],
            "test_coverage": test_metrics["coverage"],
            "test_directional_accuracy": test_metrics["directional_accuracy"],
            "test_margin": test_metrics["margin"],
        }
        for key in sharpe_keys:
            if test_metrics[key] is not None:
                test_metrics_to_log[f"test_{key}"] = float(test_metrics[key])
        if len(seed_results) > 1:
            for metric, prefix in (
                ("accuracy", "test_accuracy"),
                ("directional_accuracy", "test_directional_accuracy"),
                ("sharpe_long_short_0bps", "test_sharpe_long_short_0bps"),
            ):
                vals = [
                    r["test_metrics"][metric]
                    for r in seed_results
                    if r["test_metrics"][metric] is not None
                ]
                if vals:
                    test_metrics_to_log[f"{prefix}_mean"] = float(np.mean(vals))
                    test_metrics_to_log[f"{prefix}_std"] = float(np.std(vals))
        mlflow_mgr.log_metrics(test_metrics_to_log)
        for class_name, f1 in test_metrics["per_class_f1"].items():
            mlflow_mgr.log_metrics({f"f1_{class_name.lower()}": f1})

        # Margin sweep curve artifact (validation Sharpe vs margin)
        margin_curve_path = "/tmp/margin_curve.json"
        with open(margin_curve_path, "w") as f:
            json.dump(best["margin_curve"], f, indent=2)
        mlflow_mgr.log_artifact(margin_curve_path, artifact_path="evaluation")

        # Plot and log artifacts
        cm_path = plot_confusion_matrix(np.array(test_metrics["confusion_matrix"]))
        mlflow_mgr.log_artifact(cm_path, artifact_path="evaluation")
        loss_path = plot_loss_curves(history["train_losses"], history["val_losses"])
        mlflow_mgr.log_artifact(loss_path, artifact_path="training")

        # --- Register model in MLflow Model Registry ---
        lstm_version = mlflow_mgr.log_model(
            model,
            registered_model_name="GlobalLSTM",
        )[1]

        mlflow_mgr.set_model_description("GlobalLSTM", model_description)
        mlflow_mgr.set_registered_model_tags(
            {
                "problem_type": "classification",
                "model_type": "GlobalLSTM_V1",
                "classes": "DOWN,FLAT,UP",
                "forecast_horizon": str(ML_CONFIG.FORECAST_HORIZON),
                "features": f"{n_features}_features_incl_vol_pct_cross_sectional",
                "window_size": str(ML_CONFIG.SEQUENCE_LENGTH),
                "framework": "pytorch",
                "threshold_mult": str(ML_CONFIG.THRESHOLD_MULT),
                "loss": "focal_loss",
                "vol_filter_percentile": str(ML_CONFIG.VOL_FILTER_PERCENTILE),
                "margin": f"{test_metrics['margin']:.2f}",
                "abstention_rule": "p_up_p_down_margin",
                "embargo_days": str(ML_CONFIG.EMBARGO_DAYS),
                "selected_seed": str(best["seed"]),
                "ensemble_size": str(len(seed_results)),
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

    finally:
        mlflow_mgr.end_run()

    logger.info(
        "Training complete — model registered",
        extra={"run_id": run_id, "model_version": lstm_version},
    )
    challenger_preds = apply_margin_rule(ens_probs, test_metrics["margin"])
    return (
        test_metrics,
        lstm_version,
        model,
        run_id,
        challenger_preds,
        [r["model"] for r in seed_results],
    )


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
            logger.error(
                "SPY missing from OHLCV data — aborting: the deployed inference "
                "path always builds 17 features (with excess returns), so a "
                "14-feature model could never be served."
            )
            return {"error": 1.0}
    except Exception:
        logger.error(
            "Failed to compute SPY features — aborting (deployed inference "
            "path requires the 17-feature layout)",
            exc_info=True,
        )
        return {"error": 1.0}

    # 5. Prepare global dataset (unnormalized — normalization happens after split)
    (global_sequences, global_labels, global_ticker_idxs, global_dates, global_fwd_rets) = (
        prepare_global_dataset(
            ohlcv_data,
            vocab,
            spy_features_df=spy_features_df,
        )
    )
    logger.info("Global dataset prepared", extra={"samples": len(global_sequences)})

    if len(global_sequences) < 100:
        logger.error("Too few samples (%d) - aborting", len(global_sequences))
        return {"error": 1.0}

    # 6. Chronological split with embargo (UNNORMALIZED — preserves ordering).
    #    The embargo drops train windows whose 5-day label windows would
    #    straddle the val/test boundaries — without it, train windows whose
    #    labels overlap val/test periods leak future information.
    train_data, val_data, test_data = chronological_split(
        global_sequences,
        global_labels,
        global_ticker_idxs,
        train_frac=ML_CONFIG.TRAIN_SPLIT,
        val_frac=ML_CONFIG.VAL_SPLIT,
        dates=global_dates,
        forward_returns=global_fwd_rets,
        embargo_days=ML_CONFIG.EMBARGO_DAYS,
    )
    logger.info(
        "Dataset split (embargo %dd) - train: %d, val: %d, test: %d",
        ML_CONFIG.EMBARGO_DAYS,
        len(train_data[0]),
        len(val_data[0]),
        len(test_data[0]),
    )

    # Optional train-only volatility regime filter (off by default — ML_VOL_FILTER).
    # Never applied to val/test: the deployed model must be evaluated on the
    # same unfiltered distribution it sees live.
    if ML_CONFIG.VOL_FILTER_PERCENTILE is not None:
        # Column 13 (0-based) of each timestep is the vol_pct feature; the
        # value at the window endpoint classifies the window's vol regime.
        vol_pct_at_end = train_data[0][:, -1, 13]
        keep = vol_pct_at_end >= ML_CONFIG.VOL_FILTER_PERCENTILE
        train_data = tuple(arr[keep] for arr in train_data)
        logger.info(
            "Train-only vol filter (>= %.2f): kept %d/%d windows",
            ML_CONFIG.VOL_FILTER_PERCENTILE,
            int(keep.sum()),
            len(keep),
        )

    # Keep raw (unnormalized) copies for champion re-scoring + reference dists
    train_features_raw = np.copy(train_data[0])
    train_labels_raw = np.copy(train_data[1])
    test_raw = tuple(np.copy(arr) for arr in test_data)

    # 7. Normalize using TRAINING stats only (fixes data leak — Issue 3)
    train_data, val_data, test_data, global_means, global_stds = fit_normalize_splits(
        train_data,
        val_data,
        test_data,
    )
    logger.info("Normalization complete — means/stds fit on training data only")

    # 8. Train LSTM, evaluate, register model (pure — no promotion logic)
    (
        test_metrics,
        model_version,
        trained_model,
        run_id,
        challenger_preds,
        seed_models,
    ) = await _run_lstm_pipeline(
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

    # ------------------------------------------------------------------
    # Champion Comparison Gate
    # ------------------------------------------------------------------
    # Paired gate (preferred): re-score the current champion on THIS test set
    # (with the champion's own normalisation/vocab), then run an exact McNemar
    # test on the discordant directional decisions of the two models over the
    # SAME windows. This fixes the old unpaired gate that compared directional
    # accuracies measured on different evaluation periods. Falls back to the
    # unpaired binomial gate only when no champion checkpoint exists yet.
    mlflow_mgr = MLflowManager()
    champion_metrics = await mlflow_mgr.read_champion_metrics()
    challenger_da = test_metrics.get("directional_accuracy", 0.0)
    champion_da = champion_metrics.get("directional_accuracy", 0.0) if champion_metrics else None

    decision = None
    gate_mode = "unpaired"
    champion_da_on_test: float | None = None
    # Same directory resolution as save_champion_to_disk (writability fallback),
    # so the gate always looks where the champion checkpoint is actually written.
    champion_path = str(mlflow_mgr._resolve_save_dir() / "model.pt")
    # A promoted ensemble writes model_seed{i}.pt siblings; load them all and
    # average — the champion must be scored the same way it serves.
    seed_paths = sorted(mlflow_mgr._resolve_save_dir().glob("model_seed*.pt"))
    if os.path.exists(champion_path) or seed_paths:
        try:
            # Re-scoring runs on CPU: loading checkpoints onto MPS crashes in
            # F.embedding ("Placeholder storage has not been allocated") and
            # CPU is plenty for a one-off gate evaluation.
            gate_device = torch.device("cpu")
            champ_models = [GlobalLSTM.load(str(p), device=gate_device) for p in seed_paths] or [
                GlobalLSTM.load(champion_path, device=gate_device)
            ]
            champion = champ_models[0]
            champ_means = champion._feature_means
            champ_stds = champion._feature_stds
            if (
                champ_means is not None
                and champ_stds is not None
                and champ_means.shape[-1] == test_raw[0].shape[-1]
            ):
                champ_seqs = np.nan_to_num((test_raw[0] - champ_means) / champ_stds, nan=0.0)
                # Remap this run's ticker indices into the champion's vocab:
                # embedding row i refers to a different ticker in each vocab,
                # so scoring the champion on this run's indices silently
                # corrupts its DA whenever the ticker universe shifts.
                inv_vocab = {idx: ticker for ticker, idx in vocab.items()}
                champ_ticker_idxs = np.array(
                    [champion._vocab.get(inv_vocab.get(int(t), ""), 0) for t in test_raw[2]],
                    dtype=np.int64,
                )
                champ_ds = SequenceDataset(champ_seqs, test_raw[1], champ_ticker_idxs)
                champ_loader = DataLoader(champ_ds, batch_size=ML_CONFIG.BATCH_SIZE, shuffle=False)
                per_model_probs = [
                    predict_probs(m, champ_loader, gate_device)[0] for m in champ_models
                ]
                champ_probs = (
                    np.mean(per_model_probs, axis=0)
                    if len(per_model_probs) > 1
                    else per_model_probs[0]
                )
                champ_margin = champion._margin if champion._margin is not None else 0.0
                champ_preds = apply_margin_rule(champ_probs, champ_margin)

                dir_mask = test_raw[1] != 1  # directional windows only
                champ_correct = (champ_preds == test_raw[1])[dir_mask]
                chall_correct = (challenger_preds == test_raw[1])[dir_mask]
                decision = decide_promotion_paired(champ_correct, chall_correct)
                gate_mode = "paired-mcnemar"
                champion_da_on_test = float(champ_correct.mean())
                logger.info(
                    "Paired gate — champion DA on this test set %.2f%%, challenger %.2f%% "
                    "(discordant b=%d c=%d, p=%.4g)",
                    champion_da_on_test * 100,
                    float(chall_correct.mean()) * 100,
                    decision.get("statistic_b", -1),
                    decision.get("statistic_c", -1),
                    decision.get("p_value") if decision.get("p_value") is not None else -1,
                )
            else:
                logger.warning(
                    "Champion checkpoint incompatible with current feature set — unpaired gate"
                )
        except Exception:
            logger.warning(
                "Paired champion re-scoring failed — falling back to unpaired gate",
                exc_info=True,
            )
    else:
        logger.info("Paired gate skipped — no champion checkpoint at %s", champion_path)

    if decision is None:
        # Statistically-gated promotion: >2pp effect size AND one-sided
        # binomial p<0.05 on directional decisions (see ml/promotion_stats.py).
        decision = should_promote(
            champion_da,
            challenger_da,
            n_directional=test_metrics.get("n_directional"),
            n_correct=test_metrics.get("n_directional_correct"),
        )
    da_improvement = decision["improvement_pp"]
    promote = decision["promote"]

    # Run sync MLflow calls in executor to avoid blocking event loop
    loop = asyncio.get_running_loop()
    gate_metrics: dict[str, float] = {
        "champion_directional_accuracy": champion_da or 0.0,
        "challenger_improvement_pp": (
            (da_improvement * 100) if da_improvement is not None else 100.0
        ),
        "promotion_p_value": decision["p_value"] if decision["p_value"] is not None else -1.0,
        "promotion_n_directional": float(test_metrics.get("n_directional") or 0),
        "gate_mode_paired": 1.0 if gate_mode == "paired-mcnemar" else 0.0,
    }
    if champion_da_on_test is not None:
        gate_metrics["champion_da_on_test"] = champion_da_on_test
    await loop.run_in_executor(
        None,
        lambda: mlflow_mgr.log_metrics(gate_metrics),
    )
    await loop.run_in_executor(
        None,
        lambda: mlflow_mgr.set_registered_model_tags(
            {
                "champion_da": f"{champion_da:.4f}" if champion_da is not None else "none",
                "challenger_da": f"{challenger_da:.4f}",
                "promoted": str(promote).lower(),
                "promotion_reason": decision["reason"],
                "promotion_p_value": f"{decision['p_value']:.4g}"
                if decision["p_value"] is not None
                else "n/a",
                "gate_mode": gate_mode,
            }
        ),
    )

    if promote:
        # Promotion: alias, disk, DB, reference distributions
        await loop.run_in_executor(
            None,
            lambda: mlflow_mgr.set_champion_alias(version=model_version),
        )
        mlflow_mgr.save_champion_to_disk(
            trained_model,
            vocab=vocab,
            feature_means=global_means,
            feature_stds=global_stds,
            margin=test_metrics.get("margin"),
            ensemble_models=seed_models,
        )
        await _record_in_db(run_id, model_version, test_metrics)

        # Compute and store reference distributions for drift detection
        # Uses pre-normalization training data only — full dataset would leak
        # test/val distribution info into the reference baseline.
        from ml.reference_distributions import (
            FEATURE_NAMES as REF_FEATURE_NAMES,
        )
        from ml.reference_distributions import (
            build_reference_from_training_data,
            store_reference_in_db,
        )

        ref = build_reference_from_training_data(
            global_sequences=train_features_raw,
            global_labels=train_labels_raw,
            feature_names=REF_FEATURE_NAMES,
        )
        dsn = ML_CONFIG.SYNC_DATABASE_URL
        import asyncpg

        ref_conn = await asyncpg.connect(dsn)
        try:
            await store_reference_in_db(ref_conn, ref, model_version)
        finally:
            await ref_conn.close()

        logger.info(
            "Champion promoted — challenger DA %.2f%% vs champion DA %s (%s)",
            challenger_da * 100,
            f"{champion_da * 100:.2f}%" if champion_da is not None else "none",
            decision["reason"],
        )
    else:
        await _record_challenger_in_db(
            run_id,
            model_version,
            test_metrics,
            champion_da=champion_da,
            challenger_da=challenger_da,
        )
        logger.info(
            "Champion unchanged — challenger DA %.2f%% vs champion DA %.2f%% (%s)",
            challenger_da * 100,
            (champion_da or 0.0) * 100,
            decision["reason"],
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


async def _record_challenger_in_db(
    run_id: str,
    model_version: str,
    metrics: dict,
    champion_da: float | None,
    challenger_da: float,
) -> None:
    """Record a non-promoted challenger in the model_registry for historical tracking."""
    import asyncpg

    dsn = ML_CONFIG.SYNC_DATABASE_URL
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO model_registry
                    (ticker, mlflow_run_id, model_version, alias, metrics)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                None,
                run_id,
                model_version,
                "challenger",
                json.dumps(
                    {
                        **metrics,
                        "champion_da": champion_da,
                        "challenger_da": challenger_da,
                        "promoted": False,
                    }
                ),
            )
    finally:
        await conn.close()
    logger.info(
        "Challenger recorded in model_registry",
        extra={"run_id": run_id, "model_version": model_version},
    )


def main() -> None:
    """Entry point for the training pipeline.

    Usage: docker compose run ml python -m ml.pipeline
    """
    metrics = asyncio.run(run_pipeline())

    if "error" in metrics:
        sys.exit(1)

    print("\n=== Training Complete ===")
    print(f"Test 3-class Accuracy: {metrics.get('accuracy', 0):.2%}")
    print(
        f"Test Directional Accuracy: {metrics.get('directional_accuracy', 0):.2%} "
        f"(coverage {metrics.get('coverage', 0):.0%}, margin {metrics.get('margin', 0):.2f})"
    )
    ls0 = metrics.get("sharpe_long_short_0bps")
    ls10 = metrics.get("sharpe_long_short_10bps")
    if ls0 is not None:
        print(f"Long-short Sharpe: {ls0:.2f} @0bps, {ls10:.2f} @10bps")
    print(f"Per-class F1: {metrics.get('per_class_f1', {})}")
    sys.exit(0)


if __name__ == "__main__":
    main()
