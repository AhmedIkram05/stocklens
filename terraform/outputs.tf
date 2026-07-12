/**
 * outputs.tf
 * StockLens — useful values printed after apply.
 */

output "ecr_repository_url" {
  description = "ECR repository URL for the backend image"
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.main.name
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "Canonical hosted zone ID of the ALB (for Route53 alias records)"
  value       = aws_lb.main.zone_id
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.main.endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint (host:port)"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = aws_elasticache_replication_group.main.port
}

output "ecs_task_execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS task IAM role (used by the application container)"
  value       = aws_iam_role.ecs_task.arn
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the DB password"
  value       = aws_secretsmanager_secret.db_password.arn
}

output "jwt_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the JWT secret key"
  value       = aws_secretsmanager_secret.jwt_secret.arn
}

output "bedrock_model_id_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Bedrock model ID"
  value       = aws_secretsmanager_secret.bedrock_model_id.arn
}

output "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Redis AUTH token"
  value       = aws_secretsmanager_secret.redis_pass.arn
}

output "receipts_bucket_name" {
  description = "S3 bucket name for receipt images"
  value       = module.s3.receipts_bucket_name
}

output "receipts_bucket_arn" {
  description = "S3 bucket ARN for receipt images"
  value       = module.s3.receipts_bucket_arn
}

output "mlflow_artifacts_bucket_name" {
  description = "S3 bucket name for MLflow artifacts"
  value       = module.s3.mlflow_artifacts_bucket_name
}

output "mlflow_artifacts_bucket_arn" {
  description = "S3 bucket ARN for MLflow artifacts"
  value       = module.s3.mlflow_artifacts_bucket_arn
}

output "drift_reports_bucket_name" {
  description = "S3 bucket name for database drift reports"
  value       = module.s3.drift_reports_bucket_name
}

output "drift_reports_bucket_arn" {
  description = "S3 bucket ARN for database drift reports"
  value       = module.s3.drift_reports_bucket_arn
}

output "vpc_id" {
  description = "VPC ID where resources are deployed"
  value       = local.vpc_id
}
