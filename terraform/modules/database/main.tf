/**
 * database/main.tf
 * StockLens — RDS PostgreSQL instance and database_url secret.
 */

resource "aws_db_subnet_group" "main" {
  name        = "${var.app_name}-${var.environment}"
  description = "Subnet group for StockLens RDS PostgreSQL"
  subnet_ids  = var.private_subnet_ids
}

resource "aws_db_instance" "main" {
  identifier = "${var.app_name}-${var.environment}"

  engine         = "postgres"
  engine_version = "18.3"
  instance_class = var.db_instance_class

  db_name  = var.app_name
  username = var.app_name
  password = var.db_password

  # Storage
  allocated_storage     = var.db_storage_gb
  max_allocated_storage = var.db_max_storage_gb
  storage_type          = "gp3"

  # Network
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.rds_sg_id]
  publicly_accessible    = false

  # High-availability
  multi_az = true

  # Backups
  backup_retention_period = 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"
  copy_tags_to_snapshot   = true

  # Safety
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.app_name}-${var.environment}-final"

  # Performance & monitoring
  auto_minor_version_upgrade   = true
  monitoring_interval          = 0
  performance_insights_enabled = false
  storage_encrypted            = true

  parameter_group_name = "default.postgres18"

  tags = {
    Name = "${var.app_name}-rds-${var.environment}"
  }
}

# Full DATABASE_URL secret — lives here because it needs the RDS endpoint
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.app_name}-database-url-${var.environment}"
  description             = "StockLens full DATABASE_URL with embedded password"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql+asyncpg://${var.app_name}:${var.db_password}@${aws_db_instance.main.endpoint}/${var.app_name}"
}
