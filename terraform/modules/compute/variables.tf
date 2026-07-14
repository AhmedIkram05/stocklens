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

variable "vpc_id" {
  description = "VPC ID for the ALB target group"
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for the ALB"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "alb_sg_id" {
  description = "Security group ID for the ALB"
  type        = string
}

variable "ecs_tasks_sg_id" {
  description = "Security group ID for ECS tasks"
  type        = string
}

variable "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  type        = string
}

variable "ecs_task_role_arn" {
  description = "ARN of the ECS task IAM role"
  type        = string
}

variable "ecs_task_role_name" {
  description = "Name of the ECS task IAM role (for policy attachment)"
  type        = string
}

variable "container_image" {
  description = "ECR image tag for the backend container"
  type        = string
}

variable "cors_origins" {
  description = "List of allowed CORS origins"
  type        = list(string)
  default     = []
}

variable "ecs_cpu" {
  description = "ECS task CPU units (Fargate)"
  type        = string
  default     = "512"
}

variable "ecs_memory" {
  description = "ECS task memory in MiB (Fargate)"
  type        = string
  default     = "1024"
}

variable "desired_count" {
  description = "Desired number of ECS task replicas"
  type        = number
  default     = 2
}

variable "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  type        = string
}

variable "redis_port" {
  description = "ElastiCache Redis port"
  type        = number
}

variable "database_url_secret_arn" {
  description = "ARN of the DATABASE_URL secret"
  type        = string
}

variable "jwt_secret_arn" {
  description = "ARN of the JWT secret"
  type        = string
}

variable "redis_pass_secret_arn" {
  description = "ARN of the Redis password secret"
  type        = string
}

variable "champion_s3_uri" {
  description = "S3 URI for champion model artifacts"
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

variable "s3_kms_key_arn" {
  description = "ARN of the KMS key for S3 encryption"
  type        = string
}

variable "key_name" {
  description = "EC2 key pair name for GPU instance SSH access (optional)"
  type        = string
  default     = ""
}
