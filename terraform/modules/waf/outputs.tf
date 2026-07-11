output "web_acl_arn" {
  value       = aws_wafv2_web_acl.main.arn
  description = "ARN of the WAF web ACL"
}

output "web_acl_id" {
  value       = aws_wafv2_web_acl.main.id
  description = "ID of the WAF web ACL"
}
