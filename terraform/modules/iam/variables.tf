variable "app_name" {
  description = "Application name — used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_region" {
  description = "AWS region for Bedrock model ARN"
  type        = string
}

variable "secret_arns" {
  description = "List of Secrets Manager secret ARNs the execution role may read"
  type        = list(string)
}

variable "champion_s3_uri" {
  description = "S3 URI for champion model artifacts (empty = skip S3 policy)"
  type        = string
  default     = ""
}

# R4: MLflow / Airflow / retraining roles
variable "mlflow_artifacts_bucket_arn" {
  description = "ARN of the MLflow artifacts S3 bucket"
  type        = string
  default     = ""
}

variable "drift_reports_bucket_arn" {
  description = "ARN of the drift reports S3 bucket"
  type        = string
  default     = ""
}

variable "s3_kms_key_arn" {
  description = "ARN of the KMS key for S3 SSE-KMS"
  type        = string
  default     = ""
}
