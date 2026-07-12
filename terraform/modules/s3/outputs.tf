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
