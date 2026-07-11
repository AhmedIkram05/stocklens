output "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS task IAM role (used by the application container)"
  value       = aws_iam_role.ecs_task.arn
}

output "ecs_task_role_name" {
  description = "Name of the ECS task IAM role (for inline policy attachments)"
  value       = aws_iam_role.ecs_task.name
}

# R4: MLflow / Airflow / retraining roles

output "mlflow_task_role_arn" {
  description = "ARN of the MLflow Fargate task IAM role"
  value       = aws_iam_role.mlflow_task.arn
}

output "mlflow_task_role_name" {
  description = "Name of the MLflow Fargate task IAM role"
  value       = aws_iam_role.mlflow_task.name
}

output "airflow_task_role_arn" {
  description = "ARN of the Airflow Fargate task IAM role"
  value       = aws_iam_role.airflow_task.arn
}

output "airflow_task_role_name" {
  description = "Name of the Airflow Fargate task IAM role"
  value       = aws_iam_role.airflow_task.name
}

output "eventbridge_ecs_role_arn" {
  description = "ARN of the IAM role for EventBridge to run ECS tasks"
  value       = aws_iam_role.eventbridge_ecs.arn
}
