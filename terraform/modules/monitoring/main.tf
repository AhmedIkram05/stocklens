/**
 * monitoring/main.tf
 * StockLens — CloudWatch alarms, dashboard, SNS alerting, and drift metric filter.
 *
 * Round 3: adds RDS alarms, ALB 4xx/latency alarms, dashboard, drift filter.
 */

# ── SNS topic and subscription ────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "${var.env}-stocklens-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── ECS CPU high alarm (R1) ──────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "${var.env}-stocklens-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "ECS CPU > 80% for 10 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }
}

# ── ECS memory high alarm (R1) ───────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "memory_high" {
  alarm_name          = "${var.env}-stocklens-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "ECS Memory > 80% for 10 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }
}

# ── ALB 5xx error alarm (R1) ─────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.env}-stocklens-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "ALB 5xx errors > 10 in 10 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = var.alb_name_suffix
  }
}

# ── ALB target 4xx rate alarm (R3) ───────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "alb_4xx" {
  alarm_name          = "${var.env}-stocklens-alb-4xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_4XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 50
  alarm_description   = "ALB target 4xx errors > 50 in 10 minutes (e.g. bad requests, auth failures)"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = var.alb_name_suffix
  }
}

# ── Latency p50 alarm (R3) ───────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "latency_p50" {
  alarm_name          = "${var.env}-stocklens-latency-p50"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  extended_statistic  = "p50"
  threshold           = 0.5
  alarm_description   = "ALB p50 latency > 500ms for 10 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = var.alb_name_suffix
  }
}

# ── Latency p99 alarm (R3) ───────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "latency_p99" {
  alarm_name          = "${var.env}-stocklens-latency-p99"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  extended_statistic  = "p99"
  threshold           = 3.0
  alarm_description   = "ALB p99 latency > 3s for 10 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = var.alb_name_suffix
  }
}

# ── RDS free storage alarm (R3) ──────────────────────────────────────
# ponytail: always created — Terraform handles unknown dimension at apply.

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "${var.env}-stocklens-rds-free-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 2147483648 # 2 GB in bytes
  alarm_description   = "RDS free storage < 2 GB"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_id
  }
}

# ── RDS connections > 80% alarm (R3) ─────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${var.env}-stocklens-rds-connections"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 40 # ~80% of default max_connections=50 for db.t4g.micro
  alarm_description   = "RDS connections > 80% of max_connections (db.t4g.micro default=50)"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_id
  }
}

# ── Drift alert metric filter (R3) ───────────────────────────────────
# Matches structlog drift alert lines: {"alert_triggered": true, ...}

resource "aws_cloudwatch_log_metric_filter" "drift_alert" {
  name           = "${var.env}-stocklens-drift-alert"
  pattern        = "{ $.alert_triggered = true }"
  log_group_name = var.ecs_log_group_name

  metric_transformation {
    name          = "DriftAlertCount"
    namespace     = "StockLens"
    value         = 1
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "drift_alert" {
  alarm_name          = "${var.env}-stocklens-drift-alert"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DriftAlertCount"
  namespace           = "StockLens"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Drift alert triggered (CloudWatch metric filter on prediction_log)"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  depends_on = [
    aws_cloudwatch_log_metric_filter.drift_alert,
  ]
}

# ── CloudWatch dashboard (R3) ────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.env}-stocklens"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric",
        x      = 0,
        y      = 0,
        width  = 12,
        height = 6,
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", { stat = "p50", label = "p50" }],
            ["AWS/ApplicationELB", "TargetResponseTime", { stat = "p90", label = "p90" }],
            ["AWS/ApplicationELB", "TargetResponseTime", { stat = "p99", label = "p99" }],
          ],
          period = 300,
          stat   = "p50",
          region = "eu-west-2",
          title  = "ALB Latency (p50/p90/p99)"
        }
      },
      {
        type   = "metric",
        x      = 12,
        y      = 0,
        width  = 12,
        height = 6,
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_2XX_Count", { stat = "Sum", label = "2xx" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_4XX_Count", { stat = "Sum", label = "4xx" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", { stat = "Sum", label = "5xx" }],
          ],
          period = 300,
          stat   = "Sum",
          region = "eu-west-2",
          title  = "ALB HTTP Status Codes"
        }
      },
      {
        type   = "metric",
        x      = 0,
        y      = 6,
        width  = 12,
        height = 6,
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", { stat = "Average", label = "CPU" }],
            ["AWS/ECS", "MemoryUtilization", { stat = "Average", label = "Memory" }],
          ],
          period     = 300,
          stat       = "Average",
          region     = "eu-west-2",
          title      = "ECS CPU / Memory",
          dimensions = ["AWS/ECS", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name]
        }
      },
      {
        type   = "metric",
        x      = 12,
        y      = 6,
        width  = 12,
        height = 6,
        properties = {
          metrics = [
            ["AWS/RDS", "DatabaseConnections", { stat = "Average", label = "Connections" }],
            ["AWS/RDS", "FreeStorageSpace", { stat = "Average", label = "Free Storage", yAxis = "right" }],
          ],
          period     = 300,
          stat       = "Average",
          region     = "eu-west-2",
          title      = "RDS Connections / Free Storage",
          dimensions = ["AWS/RDS", "DBInstanceIdentifier", var.rds_instance_id]
        }
      },
      {
        type   = "metric",
        x      = 0,
        y      = 12,
        width  = 12,
        height = 6,
        properties = {
          metrics = [
            ["AWS/ElastiCache", "CPUUtilization", { stat = "Average", label = "Redis CPU" }],
          ],
          period = 300,
          stat   = "Average",
          region = "eu-west-2",
          title  = "Redis CPU Utilisation"
        }
      },
      {
        type   = "metric",
        x      = 12,
        y      = 12,
        width  = 12,
        height = 6,
        properties = {
          metrics = [
            ["StockLens", "DriftAlertCount", { stat = "Sum", label = "Drift Alerts" }],
          ],
          period = 300,
          stat   = "Sum",
          region = "eu-west-2",
          title  = "Drift Alert Count"
        }
      },
    ]
  })
}
