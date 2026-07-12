variable "vpc_id" {
  description = "VPC ID (unused directly but anchors the module)"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for the cache subnet group"
  type        = list(string)
}

variable "redis_sg_id" {
  description = "Security group ID for Redis ingress"
  type        = string
}

variable "redis_pass" {
  description = "ElastiCache Redis AUTH token (sensitive)"
  type        = string
  sensitive   = true
}

variable "app_name" {
  description = "Application name — used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.r6g.micro"
}
