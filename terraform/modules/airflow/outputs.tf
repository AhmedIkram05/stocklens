output "airflow_webserver_service_name" {
  description = "Name of the Airflow webserver ECS service"
  value       = aws_ecs_service.webserver.name
}

output "airflow_scheduler_service_name" {
  description = "Name of the Airflow scheduler ECS service"
  value       = aws_ecs_service.scheduler.name
}

output "airflow_task_definition_arn" {
  description = "ARN of the Airflow task definition"
  value       = aws_ecs_task_definition.airflow.arn
}

output "trigger_retrain_task_definition_arn" {
  description = "ARN of the trigger-retrain task definition (for EventBridge P7)"
  value       = aws_ecs_task_definition.trigger_retrain.arn
}

output "trigger_retrain_task_definition_family" {
  description = "Family name of the trigger-retrain task definition"
  value       = aws_ecs_task_definition.trigger_retrain.family
}

output "airflow_log_group_name" {
  description = "Name of the Airflow CloudWatch log group"
  value       = aws_cloudwatch_log_group.airflow.name
}
