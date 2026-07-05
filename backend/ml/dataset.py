"""
SequenceDataset and chronological split utilities.

Each sample is a (features, label, ticker_idx) tuple where:
    features: (SEQUENCE_LENGTH, N_FEATURES) tensor
    label: int (0=DOWN, 1=FLAT, 2=UP)
    ticker_idx: int (embedding index)
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
    """

    def __init__(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        ticker_idxs: np.ndarray,
    ) -> None:
        assert len(sequences) == len(labels) == len(ticker_idxs), (
            f"Length mismatch: {len(sequences)} vs {len(labels)} vs {len(ticker_idxs)}"
        )
        self.sequences = torch.tensor(sequences, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.long)
        self.ticker_idxs = torch.tensor(ticker_idxs, dtype=torch.long)

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
) -> (
    tuple[np.ndarray, np.ndarray, np.ndarray]
    | tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
):
    """Create sliding windows from a normalised feature matrix.

    Args:
        df_normalised: numpy array (T, F) of z-scored features.
        labels: numpy array (T,) of labels for each time step.
        ticker_idxs: numpy array (T,) of ticker embedding indices.
        sequence_length: Number of time steps per window.
        dates: Optional numpy array (T,) of dates for each time step.
            When provided, returns window_dates aligned with each window.

    Returns:
        (sequences, window_labels, window_ticker_idxs) if dates is None.
        (sequences, window_labels, window_ticker_idxs, window_dates) if dates is provided.
    """
    T = df_normalised.shape[0]
    if T < sequence_length:
        empty = (
            np.empty((0, sequence_length, df_normalised.shape[1])),
            np.empty((0,)),
            np.empty((0,)),
        )
        if dates is not None:
            return (*empty, np.empty((0,)))
        return empty

    sequences = np.lib.stride_tricks.sliding_window_view(
        df_normalised, window_shape=(sequence_length, df_normalised.shape[1])
    ).squeeze(axis=1)
    window_labels = labels[sequence_length - 1 :]
    window_ticker_idxs = ticker_idxs[sequence_length - 1 :]

    valid_mask = ~np.isnan(window_labels)
    sequences = sequences[valid_mask]
    window_labels = window_labels[valid_mask]
    window_ticker_idxs = window_ticker_idxs[valid_mask]

    if dates is not None:
        window_dates = dates[sequence_length - 1 :][valid_mask]
        return (
            sequences,
            window_labels.astype(np.int64),
            window_ticker_idxs.astype(np.int64),
            window_dates,
        )

    return sequences, window_labels.astype(np.int64), window_ticker_idxs.astype(np.int64)


def chronological_split(
    sequences: np.ndarray,
    labels: np.ndarray,
    ticker_idxs: np.ndarray,
    train_frac: float = 0.7,
    val_frac: float = 0.15,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
]:
    """Chronological train/val/test split across ALL tickers (global).

    Args:
        sequences: (N, seq_len, n_features) array.
        labels: (N,) array.
        ticker_idxs: (N,) array.
        train_frac: Fraction for training.
        val_frac: Fraction for validation.

    Returns:
        (train, val, test) where each is (sequences, labels, ticker_idxs).
    """
    N = len(sequences)
    train_end = int(N * train_frac)
    val_end = train_end + int(N * val_frac)

    train = (sequences[:train_end], labels[:train_end], ticker_idxs[:train_end])
    val = (sequences[train_end:val_end], labels[train_end:val_end], ticker_idxs[train_end:val_end])
    test = (sequences[val_end:], labels[val_end:], ticker_idxs[val_end:])

    return train, val, test
