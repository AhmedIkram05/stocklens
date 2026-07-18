variable "app_name" {
  description = "Application name — used in resource naming and tags"
  type        = string
}

variable "environment" {
  description = "Deployment environment (production, staging, etc.)"
  type        = string
}

variable "db_password" {
  description = "RDS PostgreSQL master password (sensitive, optional — auto-generated if empty)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "jwt_secret_key" {
  description = "JWT signing secret key (sensitive, optional — auto-generated if empty)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "redis_pass" {
  description = "ElastiCache Redis AUTH token (sensitive, optional — auto-generated if empty)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "langsmith_api_key" {
  description = "LangSmith API key for LLM tracing (sensitive, optional — auto-generated placeholder if empty)"
  type        = string
  sensitive   = true
  default     = ""
}
