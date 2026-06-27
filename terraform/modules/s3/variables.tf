variable "environment" {
  description = "Deployment environment (production, staging, etc.)"
  type        = string
}

variable "app_name" {
  description = "Application name — used in resource naming and tags"
  type        = string
}
