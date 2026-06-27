/**
 * rds.tf
 * StockLens — RDS PostgreSQL instance.
 *
 */

resource "aws_db_subnet_group" "main" {
  name        = "${var.app_name}-${var.environment}"
  description = "Subnet group for StockLens RDS PostgreSQL"
  subnet_ids  = local.private_subnet_ids
}

resource "aws_db_instance" "main" {
  identifier = "${var.app_name}-${var.environment}"

  engine         = "postgres"
  engine_version = "18.3"
  instance_class = var.db_instance_class

  db_name  = var.app_name
  username = var.app_name
  password = var.db_password != "" ? var.db_password : random_password.db.result

  # Storage
  allocated_storage     = var.db_storage_gb
  max_allocated_storage = var.db_max_storage_gb
  storage_type          = "gp3"

  # Network
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # High-availability (disabled for cost — enable for production SLA)
  multi_az = false

  # Backups
  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"
  copy_tags_to_snapshot   = true

  # Safety
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.app_name}-${var.environment}-final"

  # Performance & monitoring
  auto_minor_version_upgrade   = true
  monitoring_interval          = 0 # Enhanced monitoring disabled for cost; set to 60 if needed
  performance_insights_enabled = false
  storage_encrypted            = true

  parameter_group_name = "default.postgres18"

  tags = {
    Name = "${var.app_name}-rds-${var.environment}"
  }
}
