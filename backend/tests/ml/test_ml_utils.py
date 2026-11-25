"""
Tests for ML utilities (device detection, seeding, vocabulary).

All tests are pure Python with no DB or MLflow dependency.
"""

from __future__ import annotations

import numpy as np
import torch

from ml.utils import (
    build_ticker_vocabulary,
    get_device,
    set_seed,
)


def test_get_device_returns_cpu_when_cuda_unavailable() -> None:
    """Without CUDA, get_device returns cpu (or mps if available)."""
    device = get_device()
    assert isinstance(device, torch.device)
    assert device.type in ("cpu", "cuda", "mps")


def test_set_seed_deterministic() -> None:
    """set_seed produces identical random values across calls."""
    set_seed(42)
    a = torch.randn(5)
    set_seed(42)
    b = torch.randn(5)
    assert torch.equal(a, b)


def test_set_seed_numpy_deterministic() -> None:
    """set_seed also fixes numpy RNG."""
    set_seed(42)
    a = np.random.randn(5)
    set_seed(42)
    b = np.random.randn(5)
    np.testing.assert_array_equal(a, b)


def test_build_vocabulary_basic() -> None:
    """build_ticker_vocabulary returns sorted mapping with UNK at index 0."""
    tickers = ["AAPL", "MSFT", "GOOGL"]
    vocab, size = build_ticker_vocabulary(tickers)
    assert vocab["<UNK>"] == 0
    assert vocab["AAPL"] == 1
    assert vocab["GOOGL"] == 2
    assert vocab["MSFT"] == 3
    assert size == 4


def test_build_vocabulary_dedupes() -> None:
    """Duplicate tickers produce a single entry."""
    tickers = ["AAPL", "AAPL", "MSFT", "AAPL"]
    vocab, size = build_ticker_vocabulary(tickers)
    assert size == 3  # UNK + AAPL + MSFT
    assert vocab["AAPL"] == 1
    assert vocab["MSFT"] == 2


def test_build_vocabulary_sorted() -> None:
    """Tickers are sorted alphabetically (not insertion order)."""
    tickers = ["MSFT", "AAPL", "GOOGL"]
    vocab, size = build_ticker_vocabulary(tickers)
    assert list(vocab.keys()) == ["<UNK>", "AAPL", "GOOGL", "MSFT"]


def test_build_vocabulary_empty() -> None:
    """Empty ticker list returns vocabulary with UNK only."""
    vocab, size = build_ticker_vocabulary([])
    assert vocab == {"<UNK>": 0}
    assert size == 1
