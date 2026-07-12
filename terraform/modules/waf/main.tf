# WAF logging to CloudWatch (CKV_AWS_192)
resource "aws_cloudwatch_log_group" "waf" {
  # checkov:skip=CKV_AWS_158:dev — KMS key not provisioned yet
  # tfsec:ignore:aws-cloudwatch-log-group-encrypted:dev — KMS key not provisioned yet
  name              = "/aws/waf/${var.env}-stocklens"
  retention_in_days = 365
}

data "aws_iam_policy_document" "waf_log_delivery" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.waf.arn}:*"]
  }
}

resource "aws_cloudwatch_log_resource_policy" "waf_log_delivery" {
  policy_name     = "${var.env}-waf-log-delivery"
  policy_document = data.aws_iam_policy_document.waf_log_delivery.json
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  resource_arn            = aws_wafv2_web_acl.main.arn
}

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

  # AWS managed rules — Known Bad Inputs (covers Log4j, CVE-2021-44228)
  rule {
    name     = "AWS-AWSManagedRulesKnownBadInputsRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesKnownBadInputsRuleSet"
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
