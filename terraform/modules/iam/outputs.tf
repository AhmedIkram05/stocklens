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
