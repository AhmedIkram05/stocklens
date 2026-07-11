output "db_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.main.endpoint
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the DATABASE_URL"
  value       = aws_secretsmanager_secret.database_url.arn
}
