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
  description = "RDS PostgreSQL master password (sensitive)"
  type        = string
  sensitive   = true
}

variable "jwt_secret_key" {
  description = "Secret key used to sign JWT tokens (sensitive)"
  type        = string
  sensitive   = true
}

variable "container_image" {
  description = "ECR image tag for the backend container (e.g., account.dkr.ecr.eu-west-2.amazonaws.com/stocklens:latest)"
  type        = string
}

variable "bedrock_model_id" {
  description = "Amazon Bedrock model ID for Claude Haiku"
  type        = string
  default     = "anthropic.claude-3-haiku-20240307-v1:0"
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
