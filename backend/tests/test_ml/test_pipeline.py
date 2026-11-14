"""Tests for ml/pipeline.py helper functions."""

from __future__ import annotations

import numpy as np


class TestRemapTickerIndices:
    """Champion-vocab remap must equal the original per-window list comprehension."""

    @staticmethod
    def _reference(ticker_idxs, source_vocab, target_vocab):
        inv = {idx: ticker for ticker, idx in source_vocab.items()}
        return np.array(
            [target_vocab.get(inv.get(int(t), ""), 0) for t in ticker_idxs],
            dtype=np.int64,
        )

    def test_matches_reference_list_comprehension(self):
        from ml.pipeline import remap_ticker_indices

        source = {"AAPL": 0, "MSFT": 1, "TSLA": 2}
        target = {"MSFT": 7, "AAPL": 3}
        idxs = np.array([0, 1, 2, 0, 2], dtype=np.int64)
        np.testing.assert_array_equal(
            remap_ticker_indices(idxs, source, target),
            self._reference(idxs, source, target),
        )

    def test_unknown_index_and_ticker_map_to_zero(self):
        from ml.pipeline import remap_ticker_indices

        out = remap_ticker_indices(np.array([5], dtype=np.int64), {"AAPL": 0}, {"AAPL": 1})
        np.testing.assert_array_equal(out, np.array([0], dtype=np.int64))

    def test_empty_input_and_empty_vocab(self):
        from ml.pipeline import remap_ticker_indices

        empty = remap_ticker_indices(np.array([], dtype=np.int64), {}, {})
        assert empty.dtype == np.int64
        assert empty.size == 0

        all_unknown = remap_ticker_indices(np.array([0, 1], dtype=np.int64), {}, {})
        np.testing.assert_array_equal(all_unknown, np.array([0, 0]))

    def test_handles_sparse_source_indices(self):
        from ml.pipeline import remap_ticker_indices

        source = {"AAPL": 0, "MSFT": 9}
        target = {"AAPL": 1, "MSFT": 2}
        np.testing.assert_array_equal(
            remap_ticker_indices(np.array([0, 9]), source, target),
            np.array([1, 2]),
        )
