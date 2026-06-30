variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones for subnets"
  type        = list(string)
}

variable "environment" {
  description = "Deployment environment (production, staging, etc.)"
  type        = string
}

variable "app_name" {
  description = "Application name — used in resource naming and tags"
  type        = string
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnet outbound traffic"
  type        = bool
  default     = true
}
