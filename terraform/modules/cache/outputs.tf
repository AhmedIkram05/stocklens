output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint (host)"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = aws_elasticache_replication_group.main.port
}
