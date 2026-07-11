variable "vpc_id" {
  description = "VPC ID (unused directly but anchors the module)"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for the DB subnet group"
  type        = list(string)
}

variable "rds_sg_id" {
  description = "Security group ID for RDS ingress"
  type        = string
}

variable "db_password" {
  description = "RDS PostgreSQL master password (sensitive)"
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

variable "db_instance_class" {
  description = "RDS PostgreSQL instance class"
  type        = string
  default     = "db.t4g.micro"
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
