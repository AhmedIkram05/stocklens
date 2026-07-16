"""
Tests for EvidentlyReporter (src.drift.evidently_reporter).

Tests are skipped when evidently is unavailable, or mock the import.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.drift.evidently_reporter import _EVIDENTLY_AVAILABLE, EvidentlyReporter


class TestEvidentlyReporterInit:
    """Tests for EvidentlyReporter initialization."""

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_init_creates_output_dir(self, tmp_path):
        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        assert reporter.output_dir.exists()

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_init_accepts_custom_output_dir(self, tmp_path):
        custom = tmp_path / "custom"
        reporter = EvidentlyReporter(output_dir=str(custom))
        assert reporter.output_dir == custom

    def test_init_raises_when_evidently_unavailable(self):
        with patch("src.drift.evidently_reporter._EVIDENTLY_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="evidently is not available"):
                EvidentlyReporter()


class TestGenerateDriftReport:
    """Tests for generate_drift_report."""

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_generates_report_with_valid_dataframes(self, tmp_path):
        import pandas as pd

        ref_df = pd.DataFrame({"feature1": [1.0, 2.0, 3.0], "feature2": [4.0, 5.0, 6.0]})
        cur_df = pd.DataFrame({"feature1": [1.1, 2.1, 3.1], "feature2": [4.1, 5.1, 6.1]})

        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        report_path, report_id = reporter.generate_drift_report(ref_df, cur_df)

        assert report_path.endswith(".html")
        assert report_id is not None
        assert len(report_id) == 36  # UUID4 length

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_report_file_created(self, tmp_path):
        import pandas as pd

        ref_df = pd.DataFrame({"feature1": [1.0, 2.0]})
        cur_df = pd.DataFrame({"feature1": [1.1, 2.1]})

        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        report_path, _ = reporter.generate_drift_report(ref_df, cur_df)

        import os

        assert os.path.exists(report_path)

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_mixed_data_types(self, tmp_path):
        import pandas as pd

        ref_df = pd.DataFrame({"num1": [1.0, 2.0], "cat1": ["a", "b"]})
        cur_df = pd.DataFrame({"num1": [1.1, 2.1], "cat1": ["a", "c"]})

        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        report_path, _ = reporter.generate_drift_report(ref_df, cur_df)

        assert os.path.exists(report_path)

    def test_generate_report_raises_when_unavailable(self):
        import pandas as pd

        with patch("src.drift.evidently_reporter._EVIDENTLY_AVAILABLE", False):
            reporter = EvidentlyReporter.__new__(EvidentlyReporter)  # bypass __init__
            reporter.output_dir = MagicMock()

            with pytest.raises(RuntimeError, match="evidently is not available"):
                reporter.generate_drift_report(pd.DataFrame(), pd.DataFrame())


class TestGetReportAsDict:
    """Tests for get_report_as_dict (placeholder implementation)."""

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_returns_empty_dict(self, tmp_path):

        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        result = reporter.get_report_as_dict("nonexistent.html")
        assert result == {}

    def test_returns_empty_dict_when_unavailable(self):
        with patch("src.drift.evidently_reporter._EVIDENTLY_AVAILABLE", False):
            reporter = EvidentlyReporter.__new__(EvidentlyReporter)
            result = reporter.get_report_as_dict("any.html")
            assert result == {}


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_single_row_dataframes(self, tmp_path):
        import pandas as pd

        ref_df = pd.DataFrame({"feature1": [1.0]})
        cur_df = pd.DataFrame({"feature1": [2.0]})

        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        report_path, _ = reporter.generate_drift_report(ref_df, cur_df)
        assert os.path.exists(report_path)

    @pytest.mark.skipif(not _EVIDENTLY_AVAILABLE, reason="evidently not available")
    def test_many_columns(self, tmp_path):
        import numpy as np
        import pandas as pd

        cols = {f"f{i}": np.random.randn(100) for i in range(20)}
        ref_df = pd.DataFrame(cols)
        cur_df = pd.DataFrame({f"f{i}": np.random.randn(100) + 0.5 for i in range(20)})

        reporter = EvidentlyReporter(output_dir=str(tmp_path))
        report_path, _ = reporter.generate_drift_report(ref_df, cur_df)
        assert os.path.exists(report_path)
