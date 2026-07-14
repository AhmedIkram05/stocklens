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

variable "airflow_task_role_arn" {
  description = "ARN of the Airflow Fargate task IAM role"
  type        = string
}

variable "airflow_sg_id" {
  description = "Security group ID for Airflow ECS tasks"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "airflow_image" {
  description = "Docker image for Airflow services"
  type        = string
  default     = "apache/airflow:2.11.0"
}

variable "airflow_sql_alchemy_conn" {
  description = "SQLAlchemy connection string for Airflow metadata database (RDS PostgreSQL)"
  type        = string
}

variable "airflow_extra_env" {
  description = "Extra environment variables to pass to Airflow containers"
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "mlflow_tracking_uri" {
  description = "MLflow tracking server URI (e.g. http://mlflow:5000)"
  type        = string
  default     = ""
}

# P7: Closed-loop drift → auto-retrain
variable "drift_alarm_name" {
  description = "Name of the drift CloudWatch alarm to trigger retraining on ALARM state"
  type        = string
  default     = ""
}

variable "ecs_cluster_arn" {
  description = "ARN of the ECS cluster (for EventBridge ECS target)"
  type        = string
  default     = ""
}

variable "eventbridge_ecs_role_arn" {
  description = "ARN of the IAM role for EventBridge to run ECS tasks"
  type        = string
  default     = ""
}

# GPU ML Training task
variable "ml_training_task_role_arn" {
  description = "ARN of the GPU ML training task IAM role"
  type        = string
  default     = ""
}

variable "ml_training_image" {
  description = "Docker image for ML training (GPU-enabled)"
  type        = string
  default     = ""
}

variable "efs_filesystem_id" {
  description = "EFS filesystem ID for model artifacts and MLflow data"
  type        = string
  default     = ""
}

# Airflow Variables (passed via environment)
variable "ecs_cluster_name" {
  description = "ECS cluster name for EcsRunTaskOperator"
  type        = string
  default     = ""
}

variable "database_url" {
  description = "Database URL for ML training container"
  type        = string
  default     = ""
}
