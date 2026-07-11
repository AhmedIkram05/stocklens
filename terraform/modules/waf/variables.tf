variable "env" {
  type        = string
  description = "Environment name (dev/staging/prod)"
}

variable "alb_arn" {
  type        = string
  description = "ARN of the ALB to associate the WAF ACL with"
}

variable "rate_limit" {
  type        = number
  description = "Max requests per 5-minute window per IP"
  default     = 2000
}

variable "rate_limit_action" {
  type        = string
  description = "Action when rate limit is exceeded: 'block' or 'count'"
  default     = "block"
}
