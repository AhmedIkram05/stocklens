output "db_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.main.endpoint
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the DATABASE_URL"
  value       = aws_secretsmanager_secret.database_url.arn
}

output "db_instance_id" {
  description = "RDS DB instance identifier (for alarm dimensions)"
  value       = aws_db_instance.main.id
}

output "db_address" {
  description = "RDS DB instance address (host only, no port)"
  value       = aws_db_instance.main.address
}

output "db_name" {
  description = "RDS database name"
  value       = aws_db_instance.main.db_name
}

output "db_username" {
  description = "RDS master username"
  value       = aws_db_instance.main.username
}
