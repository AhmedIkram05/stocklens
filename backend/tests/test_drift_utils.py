"""
Tests for S3 drift-report utilities (src.drift.utils).

All functions that call boto3 are tested with mocked clients so no AWS
credentials are required.  Pure functions are tested directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.drift.utils import build_s3_key, generate_presigned_url, upload_report_to_s3


class TestUploadReportToS3:
    """upload_report_to_s3 — bucket-configured and error paths."""

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "my-bucket")
    @patch("src.drift.utils.boto3.client")
    def test_upload_success(self, mock_boto_client: MagicMock):
        """Returns True when upload succeeds."""
        result = upload_report_to_s3("/tmp/report.html", "drift_reports/2024-01-01/report.html")
        assert result is True
        mock_boto_client.assert_called_once_with("s3")
        mock_boto_client.return_value.upload_file.assert_called_once_with(
            "/tmp/report.html",
            "my-bucket",
            "drift_reports/2024-01-01/report.html",
        )

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "")
    def test_no_bucket_configured(self):
        """Returns False when DRIFT_REPORT_S3_BUCKET is empty."""
        result = upload_report_to_s3("/tmp/report.html", "key")
        assert result is False

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", None)
    def test_no_bucket_none(self):
        """Returns False when DRIFT_REPORT_S3_BUCKET is None."""
        result = upload_report_to_s3("/tmp/report.html", "key")
        assert result is False

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "my-bucket")
    @patch("src.drift.utils.boto3.client")
    def test_upload_failure_returns_false(self, mock_boto_client: MagicMock):
        """Returns False when boto3 raises an exception."""
        mock_boto_client.return_value.upload_file.side_effect = RuntimeError("Network error")
        result = upload_report_to_s3("/tmp/report.html", "key")
        assert result is False


class TestGeneratePresignedUrl:
    """generate_presigned_url — URL generation and error paths."""

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "my-bucket")
    @patch("src.drift.utils.boto3.client")
    def test_generates_url(self, mock_boto_client: MagicMock):
        """Returns pre-signed URL when S3 is configured."""
        mock_boto_client.return_value.generate_presigned_url.return_value = (
            "https://s3.amazonaws.com/my-bucket/key?signature=abc"
        )
        url = generate_presigned_url("drift_reports/2024-01-01/report.html")
        assert url == "https://s3.amazonaws.com/my-bucket/key?signature=abc"
        mock_boto_client.return_value.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "drift_reports/2024-01-01/report.html"},
            ExpiresIn=604800,
        )

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "my-bucket")
    @patch("src.drift.utils.boto3.client")
    def test_custom_expiry(self, mock_boto_client: MagicMock):
        """Custom expires_in is passed through."""
        mock_boto_client.return_value.generate_presigned_url.return_value = "https://url"
        url = generate_presigned_url("key", expires_in=3600)
        assert url == "https://url"
        mock_boto_client.return_value.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "key"},
            ExpiresIn=3600,
        )

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "")
    def test_no_bucket_returns_none(self):
        """Returns None when no bucket configured."""
        assert generate_presigned_url("key") is None

    @patch("src.drift.utils.settings.DRIFT_REPORT_S3_BUCKET", "my-bucket")
    @patch("src.drift.utils.boto3.client")
    def test_failure_returns_none(self, mock_boto_client: MagicMock):
        """Returns None when boto3 raises."""
        mock_boto_client.return_value.generate_presigned_url.side_effect = RuntimeError("Fail")
        assert generate_presigned_url("key") is None


class TestBuildS3Key:
    """build_s3_key — pure function, no mocking needed."""

    def test_builds_key_with_date_prefix(self):
        """Key format: drift_reports/YYYY-MM-DD/filename."""
        result = build_s3_key("run-123", "drift_report.html")
        date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
        assert result == f"drift_reports/{date_prefix}/drift_report.html"

    def test_includes_run_id_in_key(self):
        """Filename in result contains the original filename."""
        result = build_s3_key("my-run", "my-report.html")
        assert "my-report.html" in result
        assert "drift_reports/" in result
