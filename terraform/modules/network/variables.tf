variable "vpc_id" {
  description = "VPC ID for all security groups"
  type        = string
}

variable "app_name" {
  description = "Application name — used in resource naming and tags"
  type        = string
}

variable "environment" {
  description = "Deployment environment (production, staging, etc.)"
  type        = string
}


variable "aws_region" {
  description = "AWS region for VPC endpoint service names."
  type        = string
  default     = "eu-west-2"
}

variable "private_subnet_ids" {
  description = "Private subnets that host the interface endpoints."
  type        = list(string)
  default     = []

  validation {
    condition     = !var.enable_vpc_endpoints || length(var.private_subnet_ids) > 0
    error_message = "private_subnet_ids is required when enable_vpc_endpoints is true."
  }
}

variable "enable_vpc_endpoints" {
  description = "Create interface endpoints so private tasks reach ECR, S3, Secrets Manager, logs and STS without NAT."
  type        = bool
  default     = false
}
