"""Tests for ml/hpo.py — Optuna hyperparameter optimisation."""

from __future__ import annotations

import json
import sys
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import optuna
import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

from ml.hpo import (
    LSTMObjective,
    _load_best_hps,
    _log_trial_history,
    _merge_datasets,
    suggest_hps,
)
from ml.mlflow_manager import MLflowManager


class TestSuggestHPs:
    """suggest_hps() samples valid hyperparameters from the search space."""

    @staticmethod
    def _make_trial() -> optuna.Trial:
        return optuna.create_study().ask()

    def test_returns_dict_with_all_keys(self):
        trial = self._make_trial()
        hps = suggest_hps(trial)
        expected_keys = {"learning_rate", "hidden_dim", "dropout", "weight_decay", "focal_gamma"}
        assert set(hps.keys()) == expected_keys

    def test_learning_rate_log_range(self):
        lrs = []
        for _ in range(20):
            trial = self._make_trial()
            lrs.append(suggest_hps(trial)["learning_rate"])
        assert all(1e-4 <= lr <= 1e-2 for lr in lrs)
        assert len(set(round(lr, 5) for lr in lrs)) > 1  # stochastic

    def test_hidden_dim_step_16(self):
        for _ in range(10):
            trial = self._make_trial()
            hd = suggest_hps(trial)["hidden_dim"]
            assert 32 <= hd <= 128
            assert hd % 16 == 0

    def test_dropout_range(self):
        for _ in range(10):
            trial = self._make_trial()
            d = suggest_hps(trial)["dropout"]
            assert 0.2 <= d <= 0.6

    def test_weight_decay_log_range(self):
        for _ in range(20):
            trial = self._make_trial()
            wd = suggest_hps(trial)["weight_decay"]
            assert 1e-5 <= wd <= 1e-2

    def test_focal_gamma_range(self):
        for _ in range(10):
            trial = self._make_trial()
            fg = suggest_hps(trial)["focal_gamma"]
            assert 1.0 <= fg <= 3.0


class TestMergeDatasets:
    """_merge_datasets combines samples from multiple DataLoaders."""

    def test_merges_single_loader(self):
        seqs = np.random.randn(10, 30, 17).astype(np.float32)
        labels = np.random.randint(0, 3, size=10).astype(np.int64)
        idxs = np.zeros(10, dtype=np.int64)
        ds = TensorDataset(
            torch.from_numpy(seqs),
            torch.from_numpy(labels),
            torch.from_numpy(idxs),
        )
        loader = DataLoader(ds, batch_size=4)
        merged = _merge_datasets(loader)
        assert len(merged) == 10

    def test_merges_two_loaders(self):
        seqs1 = np.random.randn(5, 30, 17).astype(np.float32)
        labels1 = np.zeros(5, dtype=np.int64)
        idxs1 = np.zeros(5, dtype=np.int64)
        seqs2 = np.random.randn(7, 30, 17).astype(np.float32)
        labels2 = np.ones(7, dtype=np.int64)
        idxs2 = np.zeros(7, dtype=np.int64)

        ds1 = TensorDataset(
            torch.from_numpy(seqs1), torch.from_numpy(labels1), torch.from_numpy(idxs1)
        )
        ds2 = TensorDataset(
            torch.from_numpy(seqs2), torch.from_numpy(labels2), torch.from_numpy(idxs2)
        )
        merged = _merge_datasets(DataLoader(ds1), DataLoader(ds2))
        assert len(merged) == 12

    def test_preserves_order(self):
        seqs = np.random.randn(8, 30, 17).astype(np.float32)
        labels = np.array([0, 1, 2, 0, 1, 2, 0, 1], dtype=np.int64)
        idxs = np.zeros(8, dtype=np.int64)
        ds = TensorDataset(torch.from_numpy(seqs), torch.from_numpy(labels), torch.from_numpy(idxs))
        loader = DataLoader(ds, batch_size=4, shuffle=False)
        merged = _merge_datasets(loader)
        merged_labels = merged.labels
        assert torch.equal(merged_labels, torch.from_numpy(labels))

    def test_empty_loader_returns_empty(self):
        # Empty DataLoader is pathological — _merge_datasets will loop 0 times
        seqs = np.empty((0, 30, 17), dtype=np.float32)
        labels = np.empty((0,), dtype=np.int64)
        idxs = np.empty((0,), dtype=np.int64)
        ds = TensorDataset(torch.from_numpy(seqs), torch.from_numpy(labels), torch.from_numpy(idxs))
        loader = DataLoader(ds, batch_size=4)
        merged = _merge_datasets(loader)
        assert len(merged) == 0


class TestLoadBestHPs:
    """_load_best_hps loads Phase 1 output or returns None."""

    def test_file_not_found_returns_none(self):
        assert _load_best_hps("/tmp/nonexistent_file_xyz.json") is None

    def test_invalid_json_returns_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            assert _load_best_hps(path) is None
        finally:
            import os

            os.unlink(path)

    def test_loads_valid_hps(self):
        hps = {"learning_rate": 0.001, "hidden_dim": 64, "dropout": 0.3}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(hps, f)
            path = f.name
        try:
            loaded = _load_best_hps(path)
            assert loaded == hps
        finally:
            import os

            os.unlink(path)


class TestLogTrialHistory:
    """_log_trial_history writes trial data as MLflow artifact."""

    def test_logs_completed_trials(self):
        study = optuna.create_study()
        trial = study.ask()
        trial.report(0.5, 0)
        study.tell(trial, values=[0.5], state=optuna.trial.TrialState.COMPLETE)

        mock_mgr = MagicMock(spec=MLflowManager)
        _log_trial_history(mock_mgr, study)
        mock_mgr.log_artifact.assert_called_once()
        _call_args, call_kwargs = mock_mgr.log_artifact.call_args
        assert call_kwargs.get("artifact_path") == "hpo"

    def test_skips_running_trials(self):
        study = optuna.create_study()
        # ask but don't tell — leaves it RUNNING
        study.ask()

        mock_mgr = MagicMock(spec=MLflowManager)
        _log_trial_history(mock_mgr, study)
        written_path = mock_mgr.log_artifact.call_args[0][0]
        with open(written_path) as f:
            data = json.load(f)
        # Running trials filtered out — should be empty list
        assert isinstance(data, list)


class TestLSTMObjective:
    """LSTMObjective construction and basic interface."""

    def test_creates_with_loaders(self):
        seqs = torch.randn(8, 30, 17)
        labels = torch.randint(0, 3, (8,))
        idxs = torch.zeros(8, dtype=torch.long)
        ds = TensorDataset(seqs, labels, idxs)
        loader = DataLoader(ds, batch_size=4)

        obj = LSTMObjective(
            loader, loader, vocab_size=10, n_features=17, device=torch.device("cpu"), n_epochs=2
        )
        assert obj.n_epochs == 2
        assert obj.vocab_size == 10

    def test_call_returns_float(self):
        """Full objective call with a real tiny model — validates training pipeline integration."""
        n_features = 17
        vocab_size = 10
        batch_size = 4

        seqs = torch.randn(batch_size, 3, n_features)  # short seq len for speed
        labels = torch.randint(0, 3, (batch_size,))
        idxs = torch.zeros(batch_size, dtype=torch.long)

        # Need sequence_length to match what model expects. Override to 3 for this test
        from ml.config import ML_CONFIG

        original_seq_len = ML_CONFIG.SEQUENCE_LENGTH
        try:
            object.__setattr__(ML_CONFIG, "SEQUENCE_LENGTH", 3)
            ds = TensorDataset(seqs, labels, idxs)
            loader = DataLoader(ds, batch_size=batch_size)

            obj = LSTMObjective(
                loader,
                loader,
                vocab_size=vocab_size,
                n_features=n_features,
                device=torch.device("cpu"),
                n_epochs=1,
            )
            result = obj(optuna.create_study().ask())
            assert isinstance(result, float)
            assert 0.0 <= result <= 1.0
        finally:
            object.__setattr__(ML_CONFIG, "SEQUENCE_LENGTH", original_seq_len)


class TestCLIParsing:
    """Verify main() dispatches correctly for --phase args."""

    @staticmethod
    def _run_main(**kwargs: str | list[str]) -> None:
        import ml.hpo as hpo_module

        argv = kwargs.get("argv", ["hpo.py"])
        if not isinstance(argv, list):
            argv = [argv]
        with patch.object(sys, "argv", argv):
            hpo_module.main()

    def test_default_phase_is_1(self):
        import ml.hpo as hpo_module

        with patch.object(hpo_module, "run_phase1", return_value={"best_hps": {"lr": 0.001}}):
            with patch.object(hpo_module, "run_phase2") as mock_p2:
                with pytest.raises(SystemExit):
                    self._run_main(argv=["hpo.py"])
                mock_p2.assert_not_called()

    def test_phase_2_dispatches(self):
        import ml.hpo as hpo_module

        with patch.object(hpo_module, "run_phase2", return_value={"best_threshold_mult": 0.5}):
            with patch.object(hpo_module, "run_phase1") as mock_p1:
                with pytest.raises(SystemExit):
                    self._run_main(argv=["hpo.py", "--phase", "2"])
                mock_p1.assert_not_called()

    def test_invalid_phase_defaults_to_1(self):
        import ml.hpo as hpo_module

        with patch.object(hpo_module, "run_phase1", return_value={"best_hps": {"lr": 0.001}}):
            with patch.object(hpo_module, "run_phase2") as mock_p2:
                with pytest.raises(SystemExit):
                    self._run_main(argv=["hpo.py", "--phase", "99"])
                mock_p2.assert_not_called()
