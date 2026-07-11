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
