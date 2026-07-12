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

variable "ecs_cluster_id" {
  description = "ECS cluster ID"
  type        = string
}

variable "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution IAM role (shared with API tasks)"
  type        = string
}

variable "mlflow_task_role_arn" {
  description = "ARN of the MLflow Fargate task IAM role"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "mlflow_sg_id" {
  description = "Security group ID for MLflow ECS tasks"
  type        = string
}

variable "mlflow_backend_store_uri" {
  description = "PostgreSQL URI for MLflow backend store (e.g. postgresql://host/dbname)"
  type        = string
}

variable "mlflow_artifact_root" {
  description = "S3 URI for MLflow artifact root (e.g. s3://bucket/mlflow/)"
  type        = string
}

variable "sd_namespace_id" {
  description = "ID of the Cloud Map private DNS namespace"
  type        = string
}
