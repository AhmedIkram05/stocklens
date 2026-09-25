"""
Simple ML baselines for the same 5-day directional task the GlobalLSTM solves.

Logistic Regression and HistGradientBoosting on the flattened (30 × 17)
feature window. They answer one question: does the LSTM beat cheap
classical models on identical splits, normalisation and metrics? Reuses the
HPO data pipeline so the comparison is apples-to-apples.

Usage:
    python -m ml.baselines
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from ml.evaluate import evaluate_from_probs
from ml.hpo import _prepare_data
from ml.mlflow_manager import MLflowManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)


def _flatten(seqs: np.ndarray) -> np.ndarray:
    """(n, seq_len, n_features) → (n, seq_len * n_features)."""
    return seqs.reshape(seqs.shape[0], -1)


def _run_baseline(
    name: str,
    model,
    X_train: np.ndarray,
    y_train: np.ndarray,
    data: dict,
) -> dict:
    """Fit on train, predict_proba on test, evaluate with shared metrics."""
    logger.info("Training %s …", name)
    model.fit(X_train, y_train)

    test_data = data["test_data"]
    probs = model.predict_proba(_flatten(test_data[0]))
    metrics = evaluate_from_probs(
        probs,
        test_data[1],
        margin=0.0,
        fwd_rets=test_data[4],
        dates=test_data[3],
        ticker_idxs=test_data[2],
    )
    logger.info(
        "%s → acc=%.4f dir_acc=%.4f cov=%.2f",
        name,
        metrics["accuracy"],
        metrics["directional_accuracy"],
        metrics["coverage"],
    )
    return metrics


async def run_baselines() -> dict[str, dict]:
    data = await _prepare_data()
    train_data = data["train_data"]
    X_train = _flatten(train_data[0])
    y_train = train_data[1].astype(int)

    baselines = {
        "logistic_regression": LogisticRegression(
            max_iter=3000, class_weight="balanced"
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.1, early_stopping=True, random_state=42
        ),
    }

    results: dict[str, dict] = {}
    for name, model in baselines.items():
        results[name] = _run_baseline(name, model, X_train, y_train, data)

    # Log everything to the same experiment for side-by-side comparison.
    mgr = MLflowManager()
    mgr.start_run(run_name="baselines_h5")
    try:
        for name, metrics in results.items():
            mgr.log_metrics(
                {f"{name}_{k}": v for k, v in metrics.items() if isinstance(v, (int, float))}
            )
    finally:
        mgr.end_run()

    print("\n=== Baselines vs LSTM (test set, identical splits) ===")
    for name, m in results.items():
        print(
            f"{name:24s} 3-class acc={m['accuracy']:.2%}  "
            f"dir acc={m['directional_accuracy']:.2%}  cov={m['coverage']:.2f}"
        )
    return results


def main() -> None:
    asyncio.run(run_baselines())


if __name__ == "__main__":
    main()
