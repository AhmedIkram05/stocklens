/**
 * elasticache.tf
 * StockLens — ElastiCache Redis for caching and rate-limiting.
 *
 * Clustered Mode is disabled (single shard) which is sufficient for
 * the StockLens workload. Switch to Clustered Mode if cache exceeds
 * the node's memory limits.
 */

resource "aws_elasticache_subnet_group" "main" {
  name        = "${var.app_name}-${var.environment}"
  description = "Subnet group for StockLens ElastiCache Redis"
  subnet_ids  = local.private_subnet_ids
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
  security_group_ids = [aws_security_group.redis.id]

  # Cluster Mode disabled (single shard, no replicas).
  # To enable clustered mode: set num_node_groups + replicas_per_node_group
  # and switch to a node type that supports clustering (e.g., cache.r6g.*).
  # Multi-AZ auto-failover disabled for single-node dev.
  # Set num_cache_clusters = 2 and multi_az_enabled = true for HA.
  multi_az_enabled           = false
  automatic_failover_enabled = false

  # Maintenance
  maintenance_window         = "sun:05:00-sun:06:00"
  snapshot_window            = "04:00-05:00"
  snapshot_retention_limit   = 3
  auto_minor_version_upgrade = true

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = var.redis_pass != "" ? var.redis_pass : random_password.redis.result

  tags = {
    Name = "${var.app_name}-redis-${var.environment}"
  }
}
