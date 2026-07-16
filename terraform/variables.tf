/**
 * variables.tf
 * StockLens — all input variables.
 */

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-west-2"
}

variable "environment" {
  description = "Deployment environment (production, staging, etc.)"
  type        = string
  default     = "production"
}

variable "app_name" {
  description = "Application name — used in resource naming and tags"
  type        = string
  default     = "stocklens"
}

variable "db_password" {
  description = "RDS PostgreSQL master password (sensitive — auto-generated if empty)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "jwt_secret_key" {
  description = "Secret key used to sign JWT tokens (sensitive — auto-generated if empty)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "container_image" {
  description = "ECR image tag for the backend container (e.g., account.dkr.ecr.eu-west-2.amazonaws.com/stocklens:latest)"
  type        = string
}

variable "airflow_image" {
  description = "ECR image tag for the Airflow container (e.g., account.dkr.ecr.eu-west-2.amazonaws.com/stocklens-dev:airflow-latest)"
  type        = string
  default     = "apache/airflow:2.11.0"
}

variable "ml_training_image" {
  description = "ECR image tag for the GPU ML training container (e.g., account.dkr.ecr.eu-west-2.amazonaws.com/stocklens-dev:ml-training-latest)"
  type        = string
  default     = ""
}

variable "sagemaker_image" {
  description = "ECR image tag for the ARM64 SageMaker serving container (e.g., account.dkr.ecr.eu-west-2.amazonaws.com/stocklens-dev:sagemaker-latest)"
  type        = string
  default     = ""
}

variable "cors_origins" {
  description = "List of allowed CORS origins (e.g., https://app.stocklens.com)"
  type        = list(string)
  default     = []
}

variable "availability_zones" {
  description = "Availability zones for VPC subnets"
  type        = list(string)
  default     = ["eu-west-2a", "eu-west-2b"]
}

variable "vpc_id" {
  description = "Existing VPC ID (leave empty to create via VPC module)"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of existing private subnet IDs (leave empty to create via VPC module)"
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "List of existing public subnet IDs (leave empty to create via VPC module)"
  type        = list(string)
  default     = []
}

variable "db_instance_class" {
  description = "RDS PostgreSQL instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.r6g.micro"
}

variable "redis_pass" {
  description = "ElastiCache Redis AUTH token (sensitive)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ecs_cpu" {
  description = "ECS task CPU units (Fargate)"
  type        = string
  default     = "256"
}

variable "ecs_memory" {
  description = "ECS task memory in MiB (Fargate)"
  type        = string
  default     = "512"
}

variable "desired_count" {
  description = "Desired number of ECS task replicas"
  type        = number
  default     = 2
}

variable "db_storage_gb" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_max_storage_gb" {
  description = "RDS maximum storage autoscaling limit in GB"
  type        = number
  default     = 100
}

# ── Budgets ──

variable "budget_monthly_limit" {
  description = "Monthly budget limit in USD"
  type        = string
  default     = "100"
}

variable "budget_sns_arns" {
  description = "List of SNS topic ARNs for budget alerts"
  type        = list(string)
  default     = []
}

variable "budget_sns_arn" {
  description = "Single SNS topic ARN for cost anomaly alerts"
  type        = string
  default     = ""
}

# ── Monitoring ──

variable "alert_email" {
  description = "Email address for CloudWatch alarm notifications"
  type        = string
  default     = ""
}

# ── Champion S3 delivery ──

variable "champion_s3_uri" {
  description = "S3 URI for champion model artifacts (e.g. s3://stocklens-champion-prod/)"
  type        = string
  default     = ""
}

# ── Auto Scaling (R3) ──

variable "ecs_min_capacity" {
  description = "Minimum number of ECS tasks (HA requires ≥ 2 for AZ spread)"
  type        = number
  default     = 2
}

variable "ecs_max_capacity" {
  description = "Maximum number of ECS tasks (cost-bounded by budget guardrail)"
  type        = number
  default     = 6
}

variable "ecs_cpu_target" {
  description = "Target CPU utilisation percentage for auto scaling"
  type        = number
  default     = 70
}

variable "ecs_rps_target" {
  description = "Target request count per task for auto scaling"
  type        = number
  default     = 100
}

# ── OIDC Deploy (R5) ──

variable "github_repo" {
  description = "GitHub repository in owner/repo format for OIDC deploy role trust policy"
  type        = string
  default     = "AhmedIkram05/stocklens"
}

variable "key_name" {
  description = "EC2 key pair name for SSH access to GPU instances (optional — leave empty for no SSH)"
  type        = string
  default     = ""
}

# ── R6: SageMaker ──

variable "sagemaker_instance_type" {
  description = "Instance type for provisioned SageMaker endpoint (e.g., ml.m5.xlarge, ml.g5.xlarge)"
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
