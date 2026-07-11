output "mlflow_service_name" {
  description = "Name of the MLflow ECS service"
  value       = aws_ecs_service.mlflow.name
}

output "mlflow_task_definition_arn" {
  description = "ARN of the MLflow task definition"
  value       = aws_ecs_task_definition.mlflow.arn
}

output "mlflow_upgrade_task_definition_arn" {
  description = "ARN of the MLflow DB upgrade one-off task definition"
  value       = aws_ecs_task_definition.mlflow_upgrade.arn
}

output "mlflow_log_group_name" {
  description = "Name of the MLflow CloudWatch log group"
  value       = aws_cloudwatch_log_group.mlflow.name
}

output "mlflow_task_definition_family" {
  description = "Family name of the MLflow task definition"
  value       = local.family
}

output "mlflow_tracking_uri" {
  description = "MLflow tracking server URI for Airflow integration (http://mlflow.stocklens.internal:5000)"
  value       = "http://${local.mlflow_dns_name}:5000"
}
