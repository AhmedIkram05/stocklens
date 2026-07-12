output "sns_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "ARN of the SNS alert topic"
}

output "cpu_alarm_arn" {
  value       = aws_cloudwatch_metric_alarm.cpu_high.arn
  description = "ARN of the CPU high alarm"
}

output "memory_alarm_arn" {
  value       = aws_cloudwatch_metric_alarm.memory_high.arn
  description = "ARN of the memory high alarm"
}

output "alb_5xx_alarm_arn" {
  value       = aws_cloudwatch_metric_alarm.alb_5xx.arn
  description = "ARN of the ALB 5xx alarm"
}

output "dashboard_name" {
  value       = aws_cloudwatch_dashboard.main.dashboard_name
  description = "Name of the CloudWatch dashboard"
}

output "drift_alarm_name" {
  value       = try(aws_cloudwatch_metric_alarm.drift_alert.alarm_name, "")
  description = "Name of the drift alert alarm"
}

output "drift_alarm_arn" {
  value       = try(aws_cloudwatch_metric_alarm.drift_alert.arn, "")
  description = "ARN of the drift alert alarm"
}
