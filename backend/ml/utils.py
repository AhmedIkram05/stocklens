"""
Shared utilities for the ML module.
"""

from __future__ import annotations

import random

import numpy as np
import torch

UNK_IDX = 0  # Unknown ticker embedding index


def get_device() -> torch.device:
    """Detect and return the best available device.

    Priority: CUDA > MPS > CPU.
    """
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def set_seed(seed: int = 42) -> None:
    """Set random seed for reproducibility across all libraries."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_ticker_vocabulary(
    tickers: list[str],
    unk_token: str = "<UNK>",
) -> tuple[dict[str, int], int]:
    """Build ticker-to-index vocabulary for entity embeddings.

    Index 0 is reserved for UNK (unknown ticker).

    Returns:
        (vocab dict mapping ticker -> index, vocab_size including UNK).
    """
    vocab = {unk_token: UNK_IDX}
    for ticker in sorted(set(tickers)):
        if ticker not in vocab:
            vocab[ticker] = len(vocab)
    return vocab, len(vocab)


def get_ticker_idx(ticker: str, vocab: dict[str, int]) -> int:
    """Get embedding index for a ticker, falling back to UNK.

    Args:
        ticker: Ticker symbol.
        vocab: Ticker-to-index vocabulary.

    Returns:
        Embedding index (UNK_IDX if ticker not in vocab).
    """
    return vocab.get(ticker.upper(), UNK_IDX)
