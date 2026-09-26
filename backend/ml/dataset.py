"""
SequenceDataset and chronological split utilities.

Each sample is a (features, label, ticker_idx) tuple where:
    features: (SEQUENCE_LENGTH, N_FEATURES) tensor
    label: int (0=DOWN, 1=FLAT, 2=UP)
    ticker_idx: int (embedding index)

Windows also carry their end date and the realised forward log return for
that date so evaluation can compute price-based Sharpe metrics instead of
label-derived proxies.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import Dataset


class SequenceDataset(Dataset):
    """PyTorch Dataset for sliding window sequences.

    Args:
        sequences: numpy array of shape (N, SEQUENCE_LENGTH, N_FEATURES).
        labels: numpy array of shape (N,) with class labels.
        ticker_idxs: numpy array of shape (N,) with ticker embedding indices.
        forward_returns: optional (N,) realised forward log return per window,
            used by evaluation for price-based Sharpe metrics.
        dates: optional (N,) window end dates, used for purge/embargo and
            date-aware portfolio construction in evaluation.
    """

    def __init__(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        ticker_idxs: np.ndarray,
        forward_returns: np.ndarray | None = None,
        dates: np.ndarray | None = None,
    ) -> None:
        assert len(sequences) == len(labels) == len(ticker_idxs), (
            f"Length mismatch: {len(sequences)} vs {len(labels)} vs {len(ticker_idxs)}"
        )
        self.sequences = torch.tensor(sequences, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.long)
        self.ticker_idxs = torch.tensor(ticker_idxs, dtype=torch.long)
        self.forward_returns = forward_returns
        self.dates = dates

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return self.sequences[idx], self.labels[idx], self.ticker_idxs[idx]


def create_sliding_windows(
    df_normalised: np.ndarray,
    labels: np.ndarray,
    ticker_idxs: np.ndarray,
    sequence_length: int = 30,
    dates: np.ndarray | None = None,
    forward_returns: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Create sliding windows from a normalised feature matrix.

    A window ending at row t covers rows t-sequence_length+1 … t and carries
    labels[t] and forward_returns[t] (the realised forward return over the
    label horizon). Windows are dropped when the label, the forward return,
    OR any feature value inside the window is NaN — early-ticker rows with
    un-warmed indicators must not reach the model as zero-filled garbage.

    Returns:
        (sequences, window_labels, window_ticker_idxs, window_dates,
        window_fwd_rets). window_dates / window_fwd_rets are empty (0,)
        arrays when dates / forward_returns were not provided.
    """
    F = df_normalised.shape[1]
    empty = (
        np.empty((0, sequence_length, F)),
        np.empty(0),
        np.empty(0),
        np.empty(0),
        np.empty(0),
    )
    T = df_normalised.shape[0]
    if T < sequence_length:
        return empty

    sequences = np.lib.stride_tricks.sliding_window_view(
        df_normalised, window_shape=(sequence_length, F)
    ).squeeze(axis=1)
    offset = sequence_length - 1
    window_labels = labels[offset:]
    window_ticker_idxs = ticker_idxs[offset:]
    window_dates = dates[offset:] if dates is not None else np.empty(0)
    window_fwd_rets = forward_returns[offset:] if forward_returns is not None else np.empty(0)

    valid = ~np.isnan(window_labels)
    valid &= ~np.isnan(sequences).any(axis=(1, 2))
    if forward_returns is not None:
        valid &= ~np.isnan(window_fwd_rets)

    return (
        sequences[valid],
        window_labels[valid].astype(np.int64),
        window_ticker_idxs[valid].astype(np.int64),
        window_dates[valid] if dates is not None else np.empty(0),
        window_fwd_rets[valid] if forward_returns is not None else np.empty(0),
    )


def chronological_split(
    sequences: np.ndarray,
    labels: np.ndarray,
    ticker_idxs: np.ndarray,
    train_frac: float = 0.7,
    val_frac: float = 0.15,
    dates: np.ndarray | None = None,
    forward_returns: np.ndarray | None = None,
    embargo_days: int = 70,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
]:
    """Chronological train/val/test split across ALL tickers (global).

    Windows are assumed sorted by end date. To prevent label leakage across
    split boundaries — a train window's label horizon reaching into the val
    (or test) label period, and sequence content straddling the boundary —
    any train window ending within ``embargo_days`` calendar days before the
    val slice is dropped, and likewise val windows before the test slice.

    Args:
        sequences: (N, seq_len, n_features) array.
        labels: (N,) array.
        ticker_idxs: (N,) array.
        train_frac: Fraction for training.
        val_frac: Fraction for validation.
        dates: (N,) window end dates. Required for embargo; without it the
            split is a plain index split (leaky — kept for compatibility).
        embargo_days: Calendar-day buffer around each boundary.

    Returns:
        (train, val, test) where each part is
        (sequences, labels, ticker_idxs, dates, forward_returns).
    """
    N = len(sequences)
    train_end = int(N * train_frac)
    val_end = train_end + int(N * val_frac)

    if dates is not None and len(dates) == N:
        embargo = np.timedelta64(embargo_days, "D")
        train_keep = dates[:train_end] < dates[train_end] - embargo
        val_keep = dates[train_end:val_end] < dates[val_end] - embargo

        empty_rets = np.empty(0)
        fwd = forward_returns if forward_returns is not None else empty_rets

        train = (
            sequences[:train_end][train_keep],
            labels[:train_end][train_keep],
            ticker_idxs[:train_end][train_keep],
            dates[:train_end][train_keep],
            fwd[:train_end][train_keep] if forward_returns is not None else empty_rets,
        )
        val = (
            sequences[train_end:val_end][val_keep],
            labels[train_end:val_end][val_keep],
            ticker_idxs[train_end:val_end][val_keep],
            dates[train_end:val_end][val_keep],
            fwd[train_end:val_end][val_keep] if forward_returns is not None else empty_rets,
        )
        test = (
            sequences[val_end:],
            labels[val_end:],
            ticker_idxs[val_end:],
            dates[val_end:],
            fwd[val_end:] if forward_returns is not None else empty_rets,
        )
        return train, val, test

    empty_rets = np.empty(0)
    fwd = forward_returns if forward_returns is not None else empty_rets
    train = (
        sequences[:train_end],
        labels[:train_end],
        ticker_idxs[:train_end],
        np.empty(0),
        fwd[:train_end] if forward_returns is not None else empty_rets,
    )
    val = (
        sequences[train_end:val_end],
        labels[train_end:val_end],
        ticker_idxs[train_end:val_end],
        np.empty(0),
        fwd[train_end:val_end] if forward_returns is not None else empty_rets,
    )
    test = (
        sequences[val_end:],
        labels[val_end:],
        ticker_idxs[val_end:],
        np.empty(0),
        fwd[val_end:] if forward_returns is not None else empty_rets,
    )
    return train, val, test
