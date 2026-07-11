/**
 * outputs.tf
 * StockLens — useful values printed after apply.
 */

output "ecr_repository_url" {
  description = "ECR repository URL for the backend image"
  value       = module.compute.ecr_repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = module.compute.ecs_cluster_name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = module.compute.ecs_service_name
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = module.compute.alb_dns_name
}

output "alb_zone_id" {
  description = "Canonical hosted zone ID of the ALB (for Route53 alias records)"
  value       = module.compute.alb_zone_id
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = module.database.db_endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint (host)"
  value       = module.cache.redis_endpoint
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = module.cache.redis_port
}

output "ecs_task_execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  value       = module.iam.ecs_execution_role_arn
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS task IAM role (used by the application container)"
  value       = module.iam.ecs_task_role_arn
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the DATABASE_URL"
  value       = module.database.db_secret_arn
}

output "jwt_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the JWT secret key"
  value       = module.secrets.jwt_secret_arn
}

output "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Redis AUTH token"
  value       = module.secrets.redis_pass_secret_arn
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

output "waf_web_acl_arn" {
  description = "ARN of the WAF web ACL"
  value       = module.waf.web_acl_arn
}

output "sns_alert_topic_arn" {
  description = "ARN of the SNS alert topic"
  value       = module.monitoring.sns_topic_arn
}

output "budget_name" {
  description = "Name of the monthly budget"
  value       = module.budgets.budget_name
}

output "mlflow_artifacts_bucket_versioning" {
  description = "Versioning status on mlflow-artifacts bucket"
  value       = "Enabled"
}

output "mlflow_service_name" {
  description = "Name of the MLflow ECS service"
  value       = module.mlflow.mlflow_service_name
}

output "mlflow_task_definition_arn" {
  description = "ARN of the MLflow task definition"
  value       = module.mlflow.mlflow_task_definition_arn
}

output "mlflow_upgrade_task_definition_arn" {
  description = "ARN of the MLflow DB upgrade one-off task definition"
  value       = module.mlflow.mlflow_upgrade_task_definition_arn
}

output "mlflow_log_group_name" {
  description = "Name of the MLflow CloudWatch log group"
  value       = module.mlflow.mlflow_log_group_name
}

output "airflow_webserver_service_name" {
  description = "Name of the Airflow webserver ECS service"
  value       = module.airflow.airflow_webserver_service_name
}

output "airflow_scheduler_service_name" {
  description = "Name of the Airflow scheduler ECS service"
  value       = module.airflow.airflow_scheduler_service_name
}

output "trigger_retrain_task_definition_arn" {
  description = "ARN of the trigger-retrain ECS task definition (EventBridge P7)"
  value       = module.airflow.trigger_retrain_task_definition_arn
}

output "airflow_log_group_name" {
  description = "Name of the Airflow CloudWatch log group"
  value       = module.airflow.airflow_log_group_name
}
