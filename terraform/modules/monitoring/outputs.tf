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
