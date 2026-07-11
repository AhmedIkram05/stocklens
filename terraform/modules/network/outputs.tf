output "alb_sg_id" {
  description = "Security group ID for the ALB"
  value       = aws_security_group.alb.id
}

output "ecs_tasks_sg_id" {
  description = "Security group ID for ECS tasks"
  value       = aws_security_group.ecs_tasks.id
}

output "rds_sg_id" {
  description = "Security group ID for RDS"
  value       = aws_security_group.rds.id
}

output "redis_sg_id" {
  description = "Security group ID for ElastiCache Redis"
  value       = aws_security_group.redis.id
}

output "mlflow_sg_id" {
  description = "Security group ID for MLflow ECS tasks"
  value       = aws_security_group.mlflow.id
}

output "airflow_sg_id" {
  description = "Security group ID for Airflow ECS tasks"
  value       = aws_security_group.airflow.id
}

output "sd_namespace_id" {
  description = "ID of the Cloud Map private DNS namespace (for ECS service discovery)"
  value       = aws_service_discovery_private_dns_namespace.stocklens.id
}
