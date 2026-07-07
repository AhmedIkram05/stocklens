"""S3 utilities for drift reports."""

from __future__ import annotations

from datetime import UTC, datetime

import boto3
import structlog

from src.config import settings

logger = structlog.get_logger()


def upload_report_to_s3(local_path: str, s3_key: str) -> bool:
    """Upload a drift report HTML file to S3.

    Returns True on success, False if S3 is not configured or upload fails.
    """
    if not settings.DRIFT_REPORT_S3_BUCKET:
        logger.warning("no_s3_bucket_configured_for_drift_reports")
        return False

    try:
        s3 = boto3.client("s3")
        s3.upload_file(local_path, settings.DRIFT_REPORT_S3_BUCKET, s3_key)
        logger.info(
            "drift_report_uploaded_to_s3",
            bucket=settings.DRIFT_REPORT_S3_BUCKET,
            key=s3_key,
        )
        return True
    except Exception as exc:
        logger.error("drift_report_s3_upload_failed", error=str(exc))
        return False


def generate_presigned_url(s3_key: str, expires_in: int = 604800) -> str | None:
    """Generate a pre-signed URL for a drift report.

    Args:
        s3_key: S3 object key.
        expires_in: Seconds until URL expiry (default 7 days).

    Returns:
        Pre-signed URL string, or None if S3 is not configured.
    """
    if not settings.DRIFT_REPORT_S3_BUCKET:
        return None

    try:
        s3 = boto3.client("s3")
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.DRIFT_REPORT_S3_BUCKET, "Key": s3_key},
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        logger.error("presigned_url_generation_failed", error=str(exc))
        return None


def build_s3_key(drift_run_id: str, filename: str) -> str:
    """Build an S3 object key for a drift report.

    Format: drift_reports/YYYY-MM-DD/filename
    """
    date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"drift_reports/{date_prefix}/{filename}"
