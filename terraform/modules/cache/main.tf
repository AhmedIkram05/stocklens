/**
 * cache/main.tf
 * StockLens — ElastiCache Redis for caching and rate-limiting.
 *
 * Clustered Mode is disabled (single shard) which is sufficient for
 * the StockLens workload. Switch to Clustered Mode if cache exceeds
 * the node's memory limits.
 */

resource "aws_elasticache_subnet_group" "main" {
  name        = "${var.app_name}-${var.environment}"
  description = "Subnet group for StockLens ElastiCache Redis"
  subnet_ids  = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.app_name}-${var.environment}"
  description          = "StockLens Redis ${var.environment}"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = 1
  parameter_group_name = "default.redis7"
  port                 = 6379

  # Network
  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [var.redis_sg_id]

  # Single-node dev — Multi-AZ enabled when num_cache_clusters >= 2
  multi_az_enabled           = false
  automatic_failover_enabled = false

  # Maintenance
  maintenance_window         = "sun:05:00-sun:06:00"
  snapshot_window            = "04:00-05:00"
  snapshot_retention_limit   = 3
  auto_minor_version_upgrade = true

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = var.redis_pass

  tags = {
    Name = "${var.app_name}-redis-${var.environment}"
  }
}
