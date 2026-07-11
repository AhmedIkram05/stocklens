/**
 * budgets/main.tf
 * StockLens — Monthly budget alert and cost anomaly detection.
 */

resource "aws_budgets_budget" "monthly" {
  name              = "${var.environment}-stocklens-monthly"
  budget_type       = "COST"
  limit_amount      = var.budget_monthly_limit
  limit_unit        = "USD"
  time_period_start = "2025-01-01_00:00"
  time_unit         = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = var.budget_sns_arns
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = var.budget_sns_arns
  }
}

resource "aws_ce_anomaly_monitor" "main" {
  name         = "${var.environment}-stocklens-anomaly"
  monitor_type = "DIMENSIONAL"
  monitor_specification = jsonencode({
    MonitorDimensions = ["SERVICE"]
  })
}

resource "aws_ce_anomaly_subscription" "main" {
  name      = "${var.environment}-stocklens-anomaly-sub"
  frequency = "IMMEDIATE"

  monitor_arn_list = [aws_ce_anomaly_monitor.main.arn]

  subscriber {
    type    = "SNS"
    address = var.budget_sns_arn
  }
}
