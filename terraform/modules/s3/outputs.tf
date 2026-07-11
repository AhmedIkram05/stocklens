output "receipts_bucket_name" {
  description = "S3 bucket name for receipt images"
  value       = aws_s3_bucket.receipts.id
}

output "receipts_bucket_arn" {
  description = "S3 bucket ARN for receipt images"
  value       = aws_s3_bucket.receipts.arn
}

output "mlflow_artifacts_bucket_name" {
  description = "S3 bucket name for MLflow artifacts"
  value       = aws_s3_bucket.mlflow_artifacts.id
}

output "mlflow_artifacts_bucket_arn" {
  description = "S3 bucket ARN for MLflow artifacts"
  value       = aws_s3_bucket.mlflow_artifacts.arn
}

output "drift_reports_bucket_name" {
  description = "S3 bucket name for database drift reports"
  value       = aws_s3_bucket.drift_reports.id
}

output "drift_reports_bucket_arn" {
  description = "S3 bucket ARN for database drift reports"
  value       = aws_s3_bucket.drift_reports.arn
}

output "s3_kms_key_arn" {
  description = "ARN of the KMS key for S3 SSE-KMS encryption"
  value       = aws_kms_key.s3.arn
}

output "s3_kms_key_id" {
  description = "Key ID of the KMS key for S3 SSE-KMS encryption"
  value       = aws_kms_key.s3.key_id
}
