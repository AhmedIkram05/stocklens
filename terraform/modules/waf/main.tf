resource "aws_wafv2_web_acl" "main" {
  name        = "${var.env}-stocklens-waf"
  description = "WAF for StockLens ${var.env}"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Rate-based rule — 2000 req/5min per IP
  rule {
    name     = "rate-limit"
    priority = 1

    dynamic "action" {
      for_each = var.rate_limit_action == "block" ? [1] : []
      content {
        block {}
      }
    }

    dynamic "action" {
      for_each = var.rate_limit_action == "count" ? [1] : []
      content {
        count {}
      }
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

  # SQL injection prevention
  rule {
    name     = "sql-injection"
    priority = 2
    action {
      block {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "SQLInjection"
      sampled_requests_enabled   = true
    }
  }

  # Common web exploits (XSS, LFI, RFI, etc.)
  rule {
    name     = "common-exploits"
    priority = 3
    action {
      block {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonExploits"
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
