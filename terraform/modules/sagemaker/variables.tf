variable "app_name" {
  description = "Application name — used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "container_image" {
  description = "ECR image tag for the backend container (reused for SageMaker)"
  type        = string
}

variable "champion_s3_uri" {
  description = "S3 URI for champion model artifacts (passed to SageMaker container env)"
  type        = string
  default     = ""
}

variable "sagemaker_execution_role_arn" {
  description = "ARN of the SageMaker execution IAM role"
  type        = string
}

variable "sagemaker_instance_type" {
  description = "Instance type for provisioned SageMaker endpoint (e.g., ml.g5.xlarge, ml.m5.xlarge)"
  type        = string
  default     = "ml.m5.xlarge"
}

variable "sagemaker_model_download_timeout" {
  description = "Timeout in seconds for model download from S3 to container (max 3600)"
  type        = number
  default     = 600
}

variable "sagemaker_container_startup_timeout" {
  description = "Timeout in seconds for container startup health check (max 3600, solves cold-start SLA)"
  type        = number
  default     = 600
}
