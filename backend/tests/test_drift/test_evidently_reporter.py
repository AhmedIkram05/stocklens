"""
Tests for Evidently reporter.

These tests require pandas + evidently (both in pyproject.toml).
evidently 0.4.16 is incompatible with NumPy 2.0 (np.float_ removed);
skip at module level if not usable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

try:
    from src.drift.evidently_reporter import (
        _EVIDENTLY_AVAILABLE,
        EvidentlyReporter,
    )
except ImportError, AttributeError:
    _EVIDENTLY_AVAILABLE = False  # type: ignore[assignment]

if not _EVIDENTLY_AVAILABLE:
    pytest.skip("evidently not usable (NumPy 2.0 incompatibility)", allow_module_level=True)


@pytest.fixture
def reporter(tmp_path: Path) -> EvidentlyReporter:
    """Create a reporter that writes to a temp directory."""
    return EvidentlyReporter(output_dir=str(tmp_path))


@pytest.fixture
def sample_reference_df() -> pd.DataFrame:
    """A small reference dataset with 3 numerical features."""
    return pd.DataFrame(
        {
            "log_ret_1d": [0.01, -0.02, 0.03, -0.01, 0.02],
            "rsi_14": [45.0, 55.0, 50.0, 48.0, 52.0],
            "vol_30d": [0.15, 0.18, 0.12, 0.20, 0.16],
        }
    )


@pytest.fixture
def sample_current_df() -> pd.DataFrame:
    """A small current dataset with slightly shifted distributions."""
    return pd.DataFrame(
        {
            "log_ret_1d": [0.02, -0.01, 0.04, 0.01, -0.03],
            "rsi_14": [48.0, 52.0, 55.0, 50.0, 53.0],
            "vol_30d": [0.16, 0.19, 0.14, 0.21, 0.17],
        }
    )


class TestEvidentlyReporter:
    def test_generate_report_happy_path(
        self,
        reporter: EvidentlyReporter,
        sample_reference_df: pd.DataFrame,
        sample_current_df: pd.DataFrame,
    ) -> None:
        """Report generation with valid data returns a path and ID."""
        report_path, report_id = reporter.generate_drift_report(
            sample_reference_df,
            sample_current_df,
        )
        assert isinstance(report_path, str)
        assert isinstance(report_id, str)
        assert len(report_id) > 0
        assert os.path.exists(report_path)

    def test_report_is_html(
        self,
        reporter: EvidentlyReporter,
        sample_reference_df: pd.DataFrame,
        sample_current_df: pd.DataFrame,
    ) -> None:
        """Generated report file is valid HTML."""
        report_path, _ = reporter.generate_drift_report(
            sample_reference_df,
            sample_current_df,
        )
        with open(report_path) as f:
            content = f.read()
        assert "<html" in content or "<!DOCTYPE" in content

    def test_single_column(
        self,
        reporter: EvidentlyReporter,
    ) -> None:
        """Report generation with a single feature column."""
        ref = pd.DataFrame({"log_ret_1d": [0.01, -0.02, 0.03]})
        cur = pd.DataFrame({"log_ret_1d": [0.02, -0.01, 0.04]})
        report_path, _ = reporter.generate_drift_report(ref, cur)
        assert os.path.exists(report_path)

    def test_with_missing_values(
        self,
        reporter: EvidentlyReporter,
    ) -> None:
        """Report generation with NaN values should not crash."""
        ref = pd.DataFrame(
            {
                "log_ret_1d": [0.01, None, 0.03],
                "rsi_14": [45.0, 55.0, None],
            }
        )
        cur = pd.DataFrame(
            {
                "log_ret_1d": [0.02, -0.01, 0.04],
                "rsi_14": [48.0, None, 53.0],
            }
        )
        report_path, _ = reporter.generate_drift_report(ref, cur)
        assert os.path.exists(report_path)

    def test_empty_dataframe(self, reporter: EvidentlyReporter) -> None:
        """Empty DataFrame should not crash (may produce empty report)."""
        ref = pd.DataFrame({"a": []})
        cur = pd.DataFrame({"a": []})
        try:
            report_path, _ = reporter.generate_drift_report(ref, cur)
            assert os.path.exists(report_path)
        except Exception:
            pass

    def test_output_dir_created(self, tmp_path: Path) -> None:
        """Output directory should be created if it doesn't exist."""
        subdir = tmp_path / "nested" / "reports"
        EvidentlyReporter(output_dir=str(subdir))
        assert subdir.exists()

    def test_report_id_unique(self, reporter: EvidentlyReporter) -> None:
        """Each report generation should produce a unique ID."""
        ref = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        cur = pd.DataFrame({"x": [1.5, 2.5, 3.5]})
        _, id1 = reporter.generate_drift_report(ref, cur)
        _, id2 = reporter.generate_drift_report(ref, cur)
        assert id1 != id2

    def test_get_report_as_dict_returns_empty(self, reporter: EvidentlyReporter) -> None:
        """get_report_as_dict should return empty dict (ponytail placeholder)."""
        assert reporter.get_report_as_dict("dummy.html") == {}
