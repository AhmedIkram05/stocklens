"""Tests for ml/dataset.py - sequence dataset and chronological split."""

from __future__ import annotations

import numpy as np
import pytest
import torch


class TestSequenceDataset:
    def test_basic_creation(self) -> None:
        from ml.dataset import SequenceDataset

        sequences = np.random.randn(100, 30, 13).astype(np.float32)
        labels = np.random.randint(0, 3, size=100)
        ticker_idxs = np.zeros(100, dtype=np.int64)

        ds = SequenceDataset(sequences, labels, ticker_idxs)
        assert len(ds) == 100
        seq, lbl, tidx = ds[0]
        assert seq.shape == (30, 13)
        assert isinstance(lbl, torch.Tensor)
        assert lbl.item() in (0, 1, 2)

    def test_empty_dataset(self) -> None:
        from ml.dataset import SequenceDataset

        ds = SequenceDataset(np.empty((0, 30, 13)), np.empty((0,)), np.empty((0,)))
        assert len(ds) == 0

    def test_length_mismatch_raises(self) -> None:
        from ml.dataset import SequenceDataset

        with pytest.raises(AssertionError):
            SequenceDataset(
                np.random.randn(10, 30, 13),
                np.random.randint(0, 3, size=5),
                np.zeros(10),
            )


class TestSlidingWindows:
    def test_basic_windows(self) -> None:
        from ml.dataset import create_sliding_windows

        data = np.random.randn(50, 3)
        labels = np.random.randint(0, 3, size=50).astype(float)
        ticker_idxs = np.zeros(50)

        seqs, labs, tidxs = create_sliding_windows(data, labels, ticker_idxs, sequence_length=30)

        assert len(seqs) <= 21
        assert seqs.shape[1:] == (30, 3)

    def test_too_short_returns_empty(self) -> None:
        from ml.dataset import create_sliding_windows

        data = np.random.randn(20, 3)
        labels = np.ones(20)
        ticker_idxs = np.zeros(20)

        seqs, _, _ = create_sliding_windows(data, labels, ticker_idxs, sequence_length=30)
        assert len(seqs) == 0

    def test_nan_labels_filtered(self) -> None:
        from ml.dataset import create_sliding_windows

        data = np.random.randn(50, 3)
        labels = np.full(50, np.nan)
        ticker_idxs = np.zeros(50)

        seqs, labs, _ = create_sliding_windows(data, labels, ticker_idxs, sequence_length=30)
        assert len(seqs) == 0
        assert len(labs) == 0


class TestChronologicalSplit:
    def test_split_ratios(self) -> None:
        from ml.dataset import chronological_split

        sequences = np.random.randn(1000, 30, 13)
        labels = np.random.randint(0, 3, size=1000)
        ticker_idxs = np.zeros(1000)

        train, val, test = chronological_split(sequences, labels, ticker_idxs)

        assert len(train[0]) == 700
        assert len(val[0]) == 150
        assert len(test[0]) == 150

    def test_split_preserves_order(self) -> None:
        from ml.dataset import chronological_split

        labels = np.arange(1000)
        sequences = np.random.randn(1000, 30, 13)
        ticker_idxs = np.zeros(1000)

        train, val, test = chronological_split(sequences, labels, ticker_idxs)

        assert train[1][0] == 0
        assert train[1][-1] == 699
        assert val[1][0] == 700
        assert test[1][0] == 850

    def test_small_dataset(self) -> None:
        from ml.dataset import chronological_split

        sequences = np.random.randn(10, 30, 13)
        labels = np.arange(10)
        ticker_idxs = np.zeros(10)

        train, val, test = chronological_split(sequences, labels, ticker_idxs)
        assert len(train[0]) + len(val[0]) + len(test[0]) == 10
