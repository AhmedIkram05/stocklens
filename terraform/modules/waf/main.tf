resource "aws_wafv2_web_acl" "main" {
  name        = "${var.env}-stocklens-waf"
  description = "WAF for StockLens ${var.env} - rate-limit only"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Rate-based rule — 2000 req/5min per IP
  rule {
    name     = "rate-limit"
    priority = 0

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "StockLensWAF"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}
