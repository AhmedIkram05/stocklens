"""Reusing the featurised base must only recompute labels."""

from __future__ import annotations

import numpy as np

from ml.pipeline import prepare_global_dataset
from tests.ml.test_ml_pipeline import _make_ohlcv_array


def _base(threshold_mult: float) -> dict:
    data = {"AAPL": _make_ohlcv_array("AAPL")}
    vocab = {"<UNK>": 0, "AAPL": 1}
    _, labels, ticker_idxs, dates, _ = prepare_global_dataset(
        data, vocab, threshold_mult=threshold_mult
    )
    return {
        "ohlcv_data": data,
        "vocab": vocab,
        "ticker_idxs": ticker_idxs,
        "dates": dates,
        "labels": labels,
    }


def test_relabel_tight_and_wide_thresholds() -> None:
    from ml.hpo import _relabel_from_base

    base = _base(2.0)
    tight = _relabel_from_base(base, 0.1)
    wide = _relabel_from_base(base, 5.0)
    assert len(tight) == len(base["dates"])
    assert (wide == 1).sum() > (tight == 1).sum()
    assert not np.isnan(tight).any()

    # Relabeling must match a direct build exactly, not just in shape.
    direct = prepare_global_dataset(
        {"AAPL": _make_ohlcv_array("AAPL")},
        {"<UNK>": 0, "AAPL": 1},
        threshold_mult=0.1,
    )[1]
    assert np.array_equal(tight, direct)
