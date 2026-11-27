"""MLflow PyFunc wrapper for the promoted seed ensemble.

The champion is the averaged probability output of every seed model, but the
registry used to store only the seed-0 reference member. This wrapper loads all
member checkpoints from the model artifacts and averages their softmax output,
so a registry version matches what serving actually runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mlflow.pyfunc
import numpy as np
import torch

from ml.model import GlobalLSTM


class GlobalLSTMEnsemble(mlflow.pyfunc.PythonModel):
    """Probability ensemble over saved ``model_seed*.pt`` checkpoints."""

    def __init__(self, member_count: int = 0) -> None:
        self.member_count = member_count
        self.models: list[GlobalLSTM] = []

    def load_context(self, context: Any) -> None:
        root = Path(context.artifacts["members"])
        paths = sorted(root.glob("model_seed*.pt"))
        if not paths:
            paths = sorted(root.glob("*.pt"))
        if not paths:
            raise ValueError(f"No ensemble members found in {root}")
        if self.member_count and len(paths) != self.member_count:
            raise ValueError(
                f"Ensemble member count mismatch: expected {self.member_count}, found {len(paths)}"
            )
        self.models = [GlobalLSTM.load(str(path), device=torch.device("cpu")) for path in paths]
        for model in self.models:
            model.eval()

    def predict(self, context: Any, model_input: Any) -> np.ndarray:
        import pandas as pd

        if not self.models:
            raise RuntimeError("load_context() must be called before predict()")
        if isinstance(model_input, pd.DataFrame):
            features = np.stack(model_input["features"].to_numpy())
            ticker_idxs = model_input["ticker_idx"].to_numpy()
        else:
            features, ticker_idxs = model_input
        features_t = torch.as_tensor(np.array(features, dtype=np.float32, copy=True))
        idxs_t = torch.as_tensor(np.array(ticker_idxs, dtype=np.int64, copy=True))
        with torch.no_grad():
            probs = [model.predict_proba(features_t, idxs_t).numpy() for model in self.models]
        return np.mean(probs, axis=0)
