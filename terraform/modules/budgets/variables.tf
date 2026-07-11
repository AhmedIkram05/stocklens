variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "budget_monthly_limit" {
  description = "Monthly budget limit in USD"
  type        = string
  default     = "100"
}

variable "budget_sns_arns" {
  description = "List of SNS topic ARNs for budget alerts"
  type        = list(string)
  default     = []
}

variable "budget_sns_arn" {
  description = "Single SNS topic ARN for cost anomaly alerts"
  type        = string
  default     = ""
}
