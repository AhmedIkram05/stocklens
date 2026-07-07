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

# ponytail: evidently 0.4.16 is incompatible with NumPy 2.0 (np.float_
# removed). Catch import errors at module level so the file stays importable
# without evidently. The constructor raises a clear error on first use.
_EVIDENTLY_AVAILABLE: bool = True
try:
    from evidently import ColumnMapping  # noqa: F401
    from evidently.metric_preset import DataDriftPreset  # noqa: F401
    from evidently.report import Report  # noqa: F401
except ImportError, AttributeError:
    _EVIDENTLY_AVAILABLE = False

logger = structlog.get_logger()


class EvidentlyReporter:
    """Generates Evidently AI drift reports.

    Args:
        output_dir: Local directory to save HTML reports.

    Raises:
        RuntimeError: If evidently is not available (e.g. NumPy 2.0
            incompatibility).
    """

    def __init__(self, output_dir: str = "/tmp/evidently_reports") -> None:
        if not _EVIDENTLY_AVAILABLE:
            raise RuntimeError(
                "evidently is not available \u2014 incompatible with NumPy 2.0. "
                "Install with: uv pip install 'numpy<2' evidently"
            )
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_drift_report(
        self,
        reference_df: pd.DataFrame,
        current_df: pd.DataFrame,
        column_mapping: ColumnMapping | None = None,  # type: ignore[name-defined]  # noqa: F821
    ) -> tuple[str, str]:
        """Generate an Evidently DataDrift report comparing two datasets.

        Args:
            reference_df: Reference (training) dataset.
            current_df: Current (production) dataset.
            column_mapping: Evidently column mapping. If None, auto-detected.

        Returns:
            (report_path, report_id) tuple.
        """
        if column_mapping is None:
            column_mapping = ColumnMapping(  # type: ignore[name-defined]  # noqa: F821
                numerical_features=list(reference_df.select_dtypes(include=["number"]).columns),
            )

        report = Report(
            metrics=[  # type: ignore[name-defined]  # noqa: F821
                DataDriftPreset(  # type: ignore[name-defined]  # noqa: F821
                    columns=column_mapping.numerical_features,
                    stattest="psi",
                    cat_stattest="psi",
                    num_stattest="psi",
                    confidence=0.95,
                ),
            ]
        )

        report.run(reference_data=reference_df, current_data=current_df)

        report_id = str(uuid.uuid4())
        report_path = str(self.output_dir / f"drift_report_{report_id}.html")
        report.save_html(report_path)

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
