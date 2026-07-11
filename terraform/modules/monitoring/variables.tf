variable "env" {
  type        = string
  description = "Environment name"
}

variable "alert_email" {
  type        = string
  description = "Email for SNS alert subscription"
  default     = ""
}

variable "ecs_cluster_name" {
  type        = string
  description = "ECS cluster name for alarm dimensions"
}

variable "ecs_service_name" {
  type        = string
  description = "ECS service name for alarm dimensions"
}

variable "alb_name_suffix" {
  type        = string
  description = "ALB name suffix for alarm dimensions (e.g. stocklens-alb-dev)"
}
