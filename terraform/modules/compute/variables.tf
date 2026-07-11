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
