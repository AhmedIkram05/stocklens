"""
Optuna hyperparameter optimization for GlobalLSTM.

Phase 1 — optimize model hyperparams (lr, hidden_dim, dropout, weight_decay,
focal_gamma) with a fixed threshold_mult. The dataset is prepared once; each
trial reinitializes the model and trains from scratch. Per-epoch validation
metrics are reported to the pruner so bad trials die early, and the objective
is the smoothed validation directional accuracy (mean of the last 3 epochs).

Phase 2 — sweep threshold_mult using the best model HPs from Phase 1.
Selection is by VALIDATION directional accuracy only; test metrics are
logged for reporting but never used for selection.

Results persist across runs: the Optuna study lives in a sqlite file under
``ml/.optuna/`` and the winning HPs in ``ml/.optuna/best_hps.json``.

Usage:
    python -m ml.hpo              # Phase 1
    python -m ml.hpo --phase 2    # Phase 2

Reference:
    https://optuna.readthedocs.io/en/stable/
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import optuna
import pandas as pd
import torch
from optuna import Trial
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler
from torch.utils.data import DataLoader

from ml.config import ML_CONFIG
from ml.dataset import SequenceDataset, chronological_split
from ml.evaluate import evaluate
from ml.features import compute_all_features
from ml.mlflow_manager import MLflowManager
from ml.model import GlobalLSTM
from ml.pipeline import (
    fetch_ohlcv_for_tickers,
    fit_normalize_splits,
    prepare_global_dataset,
)
from ml.train import train
from ml.utils import build_ticker_vocabulary, get_device, set_seed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

# Persistent results live next to the code so they survive container restarts.
_OPTUNA_DIR = Path(__file__).resolve().parent / ".optuna"
STORAGE_URI = f"sqlite:///{_OPTUNA_DIR / 'lstm_hpo.sqlite'}"
BEST_HPS_PATH = _OPTUNA_DIR / "best_hps.json"

N_TRIALS = 30
TRIAL_TIMEOUT_S = 7200
TRIAL_EPOCHS = 40

# ── Search space ──────────────────────────────────────────────────────────
# 5 dimensions, reasonable ranges based on prior runs.
# Threshold_mult is kept fixed in Phase 1 and swept separately in Phase 2.


def suggest_hps(trial: Trial) -> dict[str, Any]:
    """Sample hyperparameters from the search space."""
    return {
        "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True),
        "hidden_dim": trial.suggest_int("hidden_dim", 32, 128, step=16),
        "dropout": trial.suggest_float("dropout", 0.2, 0.6),
        "weight_decay": trial.suggest_float("weight_decay", 1e-5, 1e-2, log=True),
        "focal_gamma": trial.suggest_float("focal_gamma", 1.0, 3.0),
    }


# ── Objective ─────────────────────────────────────────────────────────────
# Dataset is fixed per study; each trial rebuilds the model and trains.


class LSTMObjective:
    """Optuna objective: train a model with trial HPs, return val_dir_acc.

    Per-epoch val directional accuracy is reported to the pruner inside the
    training loop (via the ``epoch_callback`` hook), so MedianPruner actually
    kills unpromising trials mid-run instead of after the fact.
    """

    def __init__(
        self,
        train_loader: DataLoader,
        val_loader: DataLoader,
        vocab_size: int,
        n_features: int,
        device: torch.device,
        n_epochs: int = TRIAL_EPOCHS,
    ) -> None:
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.vocab_size = vocab_size
        self.n_features = n_features
        self.device = device
        self.n_epochs = n_epochs

    def __call__(self, trial: Trial) -> float:
        hps = suggest_hps(trial)

        # Same seed every trial so HP comparisons are apples-to-apples.
        set_seed(42)

        model = GlobalLSTM(
            n_features=self.n_features,
            vocab_size=self.vocab_size,
            embed_dim=ML_CONFIG.EMBED_DIM,
            hidden_dim=hps["hidden_dim"],
            n_layers=ML_CONFIG.N_LAYERS,
            dropout=hps["dropout"],
            n_classes=ML_CONFIG.N_CLASSES,
        ).to(self.device)

        def report_epoch(epoch_idx: int, metrics: dict[str, float]) -> None:
            trial.report(metrics["val_dir_acc"], epoch_idx)
            if trial.should_prune():
                raise optuna.TrialPruned()

        history = train(
            model,
            self.train_loader,
            self.val_loader,
            n_epochs=self.n_epochs,
            lr=hps["learning_rate"],
            weight_decay=hps["weight_decay"],
            focal_gamma=hps["focal_gamma"],
            patience=10,
            min_delta=3e-3,
            device=self.device,
            epoch_callback=report_epoch,
        )

        # Smoothed val metric (mean of last 3 epochs) from the training loop.
        return history.get("best_dir_acc", 0.0)


# ── Data preparation ──────────────────────────────────────────────────────


async def _prepare_data(threshold_mult: float | None = None) -> dict[str, Any]:
    """Fetch data, prepare dataset, split with embargo, normalise.

    Returns raw split tuples, loaders, vocab and metadata so callers can run
    multiple training passes (one per trial) without refetching.
    """
    device = get_device()

    # Override threshold if provided (for Phase 2)
    if threshold_mult is not None:
        object.__setattr__(ML_CONFIG, "THRESHOLD_MULT", threshold_mult)
        logger.info("Overriding threshold_mult to %.2f", threshold_mult)

    ohlcv_data = await fetch_ohlcv_for_tickers(ML_CONFIG.TRAINING_TICKERS)
    if not ohlcv_data:
        raise RuntimeError("No OHLCV data fetched")

    tickers_with_data = list(ohlcv_data.keys())
    vocab, vocab_size = build_ticker_vocabulary(tickers_with_data)
    logger.info("Data fetched: %d tickers", len(tickers_with_data))

    # SPY is required: cross-sectional features must match the 17-feature
    # inference contract, so fail loudly instead of silently degrading.
    spy_ohlcv = await fetch_ohlcv_for_tickers([ML_CONFIG.BENCHMARK_TICKER])
    if ML_CONFIG.BENCHMARK_TICKER not in spy_ohlcv:
        raise RuntimeError("SPY data unavailable — cannot build cross-sectional features")
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
    logger.info("SPY cross-sectional features ready")

    sequences, labels, ticker_idxs, dates, fwd_rets = prepare_global_dataset(
        ohlcv_data,
        vocab,
        spy_features_df=spy_features_df,
    )
    logger.info("Dataset: %d samples", len(sequences))

    if len(sequences) < 100:
        raise RuntimeError(f"Too few samples ({len(sequences)})")

    train_data, val_data, test_data = chronological_split(
        sequences,
        labels,
        ticker_idxs,
        train_frac=ML_CONFIG.TRAIN_SPLIT,
        val_frac=ML_CONFIG.VAL_SPLIT,
        dates=dates,
        forward_returns=fwd_rets,
        embargo_days=ML_CONFIG.EMBARGO_DAYS,
    )
    train_data, val_data, test_data, means, stds = fit_normalize_splits(
        train_data,
        val_data,
        test_data,
    )

    train_loader = DataLoader(
        SequenceDataset(
            train_data[0],
            train_data[1],
            train_data[2],
            dates=train_data[3],
            forward_returns=train_data[4],
        ),
        batch_size=ML_CONFIG.BATCH_SIZE,
        shuffle=True,
    )
    val_loader = DataLoader(
        SequenceDataset(
            val_data[0],
            val_data[1],
            val_data[2],
            dates=val_data[3],
            forward_returns=val_data[4],
        ),
        batch_size=ML_CONFIG.BATCH_SIZE,
        shuffle=False,
    )
    test_loader = DataLoader(
        SequenceDataset(
            test_data[0],
            test_data[1],
            test_data[2],
            dates=test_data[3],
            forward_returns=test_data[4],
        ),
        batch_size=ML_CONFIG.BATCH_SIZE,
        shuffle=False,
    )

    return {
        "train_data": train_data,
        "val_data": val_data,
        "test_data": test_data,
        "train_loader": train_loader,
        "val_loader": val_loader,
        "test_loader": test_loader,
        "vocab": vocab,
        "vocab_size": vocab_size,
        "tickers_with_data": tickers_with_data,
        "means": means,
        "stds": stds,
        "device": device,
    }


# ── Phase 1 — model hyperparameter search ─────────────────────────────────


async def run_phase1() -> dict[str, Any]:
    """Phase 1: optimise model HPs with fixed threshold."""
    set_seed(42)
    logger.info(
        "Phase 1: optimise model hyperparameters (%.2f threshold)", ML_CONFIG.THRESHOLD_MULT
    )

    data = await _prepare_data()
    device = data["device"]

    _OPTUNA_DIR.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name="lstm_hpo_phase1",
        direction="maximize",
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=5, n_warmup_steps=5),
        storage=STORAGE_URI,
        load_if_exists=True,
    )

    objective = LSTMObjective(
        train_loader=data["train_loader"],
        val_loader=data["val_loader"],
        vocab_size=data["vocab_size"],
        n_features=ML_CONFIG.N_FEATURES,
        device=device,
    )

    logger.info("Starting optimisation (%d max trials)", N_TRIALS)
    study.optimize(objective, n_trials=N_TRIALS, timeout=TRIAL_TIMEOUT_S, show_progress_bar=True)

    best_trial = study.best_trial
    best_hps = best_trial.params

    n_pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
    logger.info(
        "Phase 1 done — best val_dir_acc=%.4f, pruned=%d/%d",
        best_trial.value,
        n_pruned,
        len(study.trials),
    )
    for k, v in best_hps.items():
        logger.info("  %s: %s", k, v)

    # ── Refit the winning HPs on train (val held out for early stopping) ──
    # Merging val into train would leave no signal for early stopping and
    # epoch selection, so the final model trains on train only.
    final_model = GlobalLSTM(
        n_features=ML_CONFIG.N_FEATURES,
        vocab_size=data["vocab_size"],
        embed_dim=ML_CONFIG.EMBED_DIM,
        hidden_dim=best_hps["hidden_dim"],
        n_layers=ML_CONFIG.N_LAYERS,
        dropout=best_hps["dropout"],
        n_classes=ML_CONFIG.N_CLASSES,
    ).to(device)

    train(
        final_model,
        data["train_loader"],
        data["val_loader"],
        n_epochs=ML_CONFIG.EPOCHS,
        lr=best_hps["learning_rate"],
        weight_decay=best_hps["weight_decay"],
        focal_gamma=best_hps["focal_gamma"],
        patience=ML_CONFIG.PATIENCE,
        min_delta=ML_CONFIG.MIN_DELTA,
        device=device,
    )

    test_data = data["test_data"]
    test_metrics = evaluate(
        final_model,
        data["test_loader"],
        device,
        margin=0.0,
        fwd_rets=test_data[4],
        dates=test_data[3],
        ticker_idxs=test_data[2],
    )
    logger.info("Test metrics: %s", test_metrics)

    # ── Log to MLflow ──
    mlflow_mgr = MLflowManager()
    mlflow_mgr.enable_autologging()
    mlflow_mgr.enable_system_metrics()
    mlflow_mgr.start_run(run_name=f"hpo_phase1_h{ML_CONFIG.FORECAST_HORIZON}")

    try:
        mlflow_mgr.log_params(best_hps)
        mlflow_mgr.log_params(
            {
                "n_features": ML_CONFIG.N_FEATURES,
                "vocab_size": data["vocab_size"],
                "sequence_length": ML_CONFIG.SEQUENCE_LENGTH,
                "forecast_horizon": ML_CONFIG.FORECAST_HORIZON,
                "n_tickers": len(data["tickers_with_data"]),
                "threshold_mult": ML_CONFIG.THRESHOLD_MULT,
                "n_trials": len(study.trials),
                "n_pruned": n_pruned,
                "phase": "1",
                "selection_metric": "val_dir_acc_smoothed",
                "selection_split": "val",
            }
        )
        sharpe_ls_0 = test_metrics.get("sharpe_long_short_0bps")
        sharpe_ls_10 = test_metrics.get("sharpe_long_short_10bps")
        mlflow_mgr.log_metrics(
            {
                "val_directional_accuracy": best_trial.value,
                "test_accuracy": test_metrics["accuracy"],
                "test_coverage": test_metrics["coverage"],
                "test_directional_accuracy": test_metrics["directional_accuracy"],
                **(
                    {
                        "test_sharpe_long_short_0bps": sharpe_ls_0,
                        "test_sharpe_long_short_10bps": sharpe_ls_10,
                    }
                    if sharpe_ls_0 is not None
                    else {}
                ),
            }
        )

        # Log trial history as artifact
        _log_trial_history(mlflow_mgr, study)
    finally:
        mlflow_mgr.end_run()

    # Persist best HPs (no champion save here — only the gated pipeline
    # promotes models; Phase 2 consumes these HPs).
    BEST_HPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BEST_HPS_PATH, "w") as f:
        json.dump(best_hps, f, indent=2, default=str)
    logger.info("Best HPs saved to %s", BEST_HPS_PATH)

    print("\n=== HPO Phase 1 Complete ===")
    print(f"Best val_dir_acc (smoothed): {best_trial.value:.2%}")
    print(f"Test 3-class accuracy:       {test_metrics['accuracy']:.2%}")
    print(f"Test dir_acc:                {test_metrics['directional_accuracy']:.2%}")
    if sharpe_ls_0 is not None:
        print(f"Test LS Sharpe @0/@10bps:    {sharpe_ls_0:.2f} / {sharpe_ls_10:.2f}")
    print(f"Best HPs:                {json.dumps(best_hps, default=str)}")
    print(f"Trials (total / pruned): {len(study.trials)} / {n_pruned}")

    return {"best_hps": best_hps, "best_val_dir_acc": best_trial.value, **test_metrics}


# ── Phase 2 — threshold_mult sweep ────────────────────────────────────────


async def run_phase2() -> dict[str, Any]:
    """Phase 2: sweep threshold_mult using the model HPs from Phase 1.

    For each threshold_mult value (0.3 → 1.0 in 0.1 steps) a dataset is
    prepared, a model trained, and VALIDATION directional accuracy recorded.
    Selection uses val only — test metrics are logged alongside for
    reporting but play no part in the choice.
    """
    set_seed(42)
    logger.info("Phase 2: sweep threshold_mult")

    # Load best HPs from Phase 1 output (if available) or use defaults.
    best_hps = _load_best_hps() or {
        "learning_rate": 0.001,
        "hidden_dim": 64,
        "dropout": 0.3,
        "weight_decay": 0.001,
        "focal_gamma": 2.0,
    }
    logger.info("Using model HPs: %s", best_hps)

    candidates = [round(x * 0.1, 1) for x in range(3, 11)]  # 0.3 … 1.0
    results: list[dict] = []

    for tmult in candidates:
        logger.info("=" * 50)
        logger.info("Sweeping threshold_mult = %.1f", tmult)

        data = await _prepare_data(threshold_mult=tmult)
        device = data["device"]

        model = GlobalLSTM(
            n_features=ML_CONFIG.N_FEATURES,
            vocab_size=data["vocab_size"],
            embed_dim=ML_CONFIG.EMBED_DIM,
            hidden_dim=best_hps["hidden_dim"],
            n_layers=ML_CONFIG.N_LAYERS,
            dropout=best_hps["dropout"],
            n_classes=ML_CONFIG.N_CLASSES,
        ).to(device)

        train(
            model,
            data["train_loader"],
            data["val_loader"],
            n_epochs=ML_CONFIG.EPOCHS,
            lr=best_hps["learning_rate"],
            weight_decay=best_hps["weight_decay"],
            focal_gamma=best_hps["focal_gamma"],
            patience=ML_CONFIG.PATIENCE,
            min_delta=ML_CONFIG.MIN_DELTA,
            device=device,
        )

        val_data = data["val_data"]
        val_metrics = evaluate(
            model,
            data["val_loader"],
            device,
            margin=0.0,
            fwd_rets=val_data[4],
            dates=val_data[3],
            ticker_idxs=val_data[2],
        )
        test_data = data["test_data"]
        test_metrics = evaluate(
            model,
            data["test_loader"],
            device,
            margin=0.0,
            fwd_rets=test_data[4],
            dates=test_data[3],
            ticker_idxs=test_data[2],
        )
        results.append(
            {
                "threshold_mult": tmult,
                "val_dir_acc": val_metrics["directional_accuracy"],
                "test_dir_acc": test_metrics["directional_accuracy"],  # reporting only
                "test_sharpe": test_metrics.get("sharpe_long_short_0bps"),
            }
        )
        logger.info(
            "  threshold=%.1f → val_dir=%.4f  test_dir=%.4f  sharpe=%s",
            tmult,
            val_metrics["directional_accuracy"],
            test_metrics["directional_accuracy"],
            test_metrics.get("sharpe_long_short_0bps"),
        )

    # Selection on VALIDATION only — the test column is informational.
    best = max(results, key=lambda r: r["val_dir_acc"])
    logger.info("=" * 50)
    logger.info(
        "Best threshold_mult: %.1f (val_dir_acc=%.4f; test_dir_acc=%.4f, reporting only)",
        best["threshold_mult"],
        best["val_dir_acc"],
        best["test_dir_acc"],
    )

    # Log to MLflow
    mlflow_mgr = MLflowManager()
    mlflow_mgr.start_run(run_name=f"hpo_phase2_h{ML_CONFIG.FORECAST_HORIZON}")
    try:
        mlflow_mgr.log_params(
            {
                **best_hps,
                "n_trials": len(candidates),
                "phase": "2",
                "selection_metric": "val_dir_acc",
                "selection_split": "val",
            }
        )
        mlflow_mgr.log_metrics(
            {
                "best_threshold_mult": best["threshold_mult"],
                "best_val_dir_acc": best["val_dir_acc"],
                "reported_test_dir_acc": best["test_dir_acc"],
            }
        )
        with open("/tmp/phase2_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        mlflow_mgr.log_artifact("/tmp/phase2_results.json", artifact_path="hpo")
    finally:
        mlflow_mgr.end_run()

    print("\n=== HPO Phase 2 Complete ===")
    print(f"Best threshold_mult: {best['threshold_mult']:.1f} (selected on val)")
    for r in results:
        print(
            f"  mult={r['threshold_mult']:.1f}  "
            f"val_dir={r['val_dir_acc']:.4f}  "
            f"test_dir={r['test_dir_acc']:.4f}"
        )

    return {"best_threshold_mult": best["threshold_mult"], "results": results}


# ── Helpers ───────────────────────────────────────────────────────────────


def _log_trial_history(mlflow_mgr: MLflowManager, study: optuna.Study) -> None:
    """Write trial history to temp JSON and log as MLflow artifact."""
    trial_data = [
        {
            "number": t.number,
            "value": t.value,
            "state": str(t.state),
            "params": t.params,
            "datetime_start": str(t.datetime_start),
            "datetime_complete": str(t.datetime_complete),
        }
        for t in study.trials
        if t.state != optuna.trial.TrialState.RUNNING
    ]
    path = "/tmp/hpo_trials.json"
    with open(path, "w") as f:
        json.dump(trial_data, f, indent=2, default=str)
    mlflow_mgr.log_artifact(path, artifact_path="hpo")


def _load_best_hps(path: Path = BEST_HPS_PATH) -> dict[str, Any] | None:
    """Load best HPs from Phase 1 output, if it exists."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Entry point ───────────────────────────────────────────────────────────


def main() -> None:
    """Run HPO. Default: Phase 1. Use --phase 2 for threshold sweep."""
    phase = "1"
    if "--phase" in sys.argv:
        idx = sys.argv.index("--phase")
        if idx + 1 < len(sys.argv):
            phase = sys.argv[idx + 1]

    if phase == "2":
        metrics = asyncio.run(run_phase2())
    else:
        metrics = asyncio.run(run_phase1())

    if not metrics:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
