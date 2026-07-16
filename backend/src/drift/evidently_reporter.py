"""
Evidently AI report generation for drift detection.

Generates DataDriftPreset reports comparing reference (training) and
current (production) data distributions. Reports are saved as HTML.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

_EVIDENTLY_AVAILABLE: bool = True
try:
    from evidently import Report  # noqa: F401
    from evidently.presets import DataDriftPreset  # noqa: F401
except (ImportError, AttributeError):
    _EVIDENTLY_AVAILABLE = False

logger = structlog.get_logger()


class EvidentlyReporter:
    """Generates Evidently AI drift reports.

    Args:
        output_dir: Local directory to save HTML reports.

    Raises:
        RuntimeError: If evidently is not available.
    """

    def __init__(self, output_dir: str = "/tmp/evidently_reports") -> None:
        if not _EVIDENTLY_AVAILABLE:
            raise RuntimeError("evidently is not available. Install with: pip install evidently")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_drift_report(
        self,
        reference_df: pd.DataFrame,
        current_df: pd.DataFrame,
    ) -> tuple[str, str]:
        """Generate an Evidently DataDrift report comparing two datasets.

        Args:
            reference_df: Reference (training) dataset.
            current_df: Current (production) dataset.

        Returns:
            (report_path, report_id) tuple.

        Raises:
            RuntimeError: If evidently is not available.
        """
        if not _EVIDENTLY_AVAILABLE:
            raise RuntimeError("evidently is not available. Install with: pip install evidently")

        preset = DataDriftPreset(  # type: ignore[name-defined]  # noqa: F821
            columns=list(reference_df.select_dtypes(include=["number"]).columns),
            num_method="psi",
            cat_method="psi",
            threshold=0.05,
        )
        report = Report(metrics=[preset])  # type: ignore[name-defined]  # noqa: F821
        result = report.run(reference_data=reference_df, current_data=current_df)

        report_id = str(uuid.uuid4())
        report_path = str(self.output_dir / f"drift_report_{report_id}.html")
        result.save_html(report_path)

        logger.info(
            "drift_report_generated",
            report_id=report_id,
            path=report_path,
            n_columns=len(reference_df.columns),
        )

        return report_path, report_id

    def get_report_as_dict(self, report_path: str) -> dict[str, Any]:
        """Get the Evidently report summary as a dict (placeholder).

        ponytail: Evidently doesn't expose a clean dict API for saved HTML reports.
        Key metrics are extracted during generation and stored in DB.
        The HTML is the primary artifact.
        """
        return {}
