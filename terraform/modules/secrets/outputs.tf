output "db_password_value" {
  description = "The effective DB password (from var or random)"
  value       = var.db_password != "" ? var.db_password : random_password.db.result
  sensitive   = true
}

output "jwt_secret_value" {
  description = "The effective JWT secret (from var or random)"
  value       = var.jwt_secret_key != "" ? var.jwt_secret_key : random_password.jwt.result
  sensitive   = true
}

output "redis_pass_value" {
  description = "The effective Redis AUTH token (from var or random)"
  value       = var.redis_pass != "" ? var.redis_pass : random_password.redis.result
  sensitive   = true
}

output "db_password_secret_arn" {
  description = "ARN of the Secrets Manager secret for DB password"
  value       = aws_secretsmanager_secret.db_password.arn
}

output "jwt_secret_arn" {
  description = "ARN of the Secrets Manager secret for JWT secret key"
  value       = aws_secretsmanager_secret.jwt_secret.arn
}

output "redis_pass_secret_arn" {
  description = "ARN of the Secrets Manager secret for Redis AUTH token"
  value       = aws_secretsmanager_secret.redis_pass.arn
}

output "langsmith_api_key_secret_arn" {
  description = "ARN of the Secrets Manager secret for LangSmith API key"
  value       = aws_secretsmanager_secret.langsmith_api_key.arn
}
