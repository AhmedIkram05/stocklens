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

variable "alb_arn_suffix" {
  type        = string
  description = "ALB ARN suffix for target group dimension"
  default     = ""
}

# RDS inputs for RDS-specific alarms
variable "rds_instance_id" {
  type        = string
  description = "RDS DB instance identifier for alarm dimensions"
  default     = ""
}

# Log group for drift metric filter
variable "ecs_log_group_name" {
  type        = string
  description = "CloudWatch log group name for ECS tasks (drift metric filter)"
  default     = ""
}
