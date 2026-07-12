# ── Data sources ──────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}

# ── KMS key for S3 SSE-KMS (R4) ──────────────────────────────────────

resource "aws_kms_key" "s3" {
  description             = "KMS key for StockLens S3 bucket SSE-KMS encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
    ]
  })
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.app_name}-s3-${var.environment}"
  target_key_id = aws_kms_key.s3.key_id
}

# ── S3 buckets ────────────────────────────────────────────────────────

resource "aws_s3_bucket" "receipts" {
  bucket = "${var.app_name}-receipts-${var.environment}"
  # checkov:skip=CKV2_AWS_62:dev — no event notifications needed for dev
  # checkov:skip=CKV_AWS_18:dev — access logging not required for receipts bucket
  # checkov:skip=CKV_AWS_144:dev — single region deployment, no cross-replication

  tags = {
    Name = "${var.app_name}-${var.environment}"
  }
}

resource "aws_s3_bucket" "mlflow_artifacts" {
  bucket = "${var.app_name}-mlflow-artifacts-${var.environment}"
  # checkov:skip=CKV2_AWS_62:dev — no event notifications needed
  # checkov:skip=CKV_AWS_18:dev — access logging not required for dev
  # checkov:skip=CKV_AWS_144:dev — cross-region replication not needed in single-region dev

  tags = {
    Name = "${var.app_name}-${var.environment}"
  }
}

resource "aws_s3_bucket" "drift_reports" {
  bucket = "${var.app_name}-drift-reports-${var.environment}"
  # checkov:skip=CKV2_AWS_62:dev — no event notifications needed
  # checkov:skip=CKV_AWS_18:dev — access logging not required for dev
  # checkov:skip=CKV_AWS_144:dev — cross-region replication not needed in single-region dev

  tags = {
    Name = "${var.app_name}-${var.environment}"
  }
}

# Ownership controls — separate resource in AWS provider v5
resource "aws_s3_bucket_ownership_controls" "receipts" {
  bucket = aws_s3_bucket.receipts.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_ownership_controls" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_ownership_controls" "drift_reports" {
  bucket = aws_s3_bucket.drift_reports.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ── Lifecycle configurations ──────────────────────────────────────────

resource "aws_s3_bucket_lifecycle_configuration" "receipts" {
  bucket = aws_s3_bucket.receipts.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "drift_reports" {
  bucket = aws_s3_bucket.drift_reports.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

# Bucket policy: enforce SecureTransport + KMS encryption on mlflow-artifacts
resource "aws_s3_bucket_policy" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.mlflow_artifacts.arn,
          "${aws_s3_bucket.mlflow_artifacts.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
      {
        Sid       = "DenyNonKMSEncryption"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.mlflow_artifacts.arn}/*"
        Condition = {
          StringNotEquals = {
            "s3:x-amz-server-side-encryption" = "aws:kms"
          }
        }
      },
    ]
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "drift_reports" {
  bucket = aws_s3_bucket.drift_reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Versioning ────────────────────────────────────────────────────────

resource "aws_s3_bucket_versioning" "receipts" {
  bucket = aws_s3_bucket.receipts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "drift_reports" {
  bucket = aws_s3_bucket.drift_reports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "drift_reports" {
  bucket = aws_s3_bucket.drift_reports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
