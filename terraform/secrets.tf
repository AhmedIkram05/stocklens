/**
 * secrets.tf
 * StockLens — Secrets Manager secrets for sensitive configuration.
 *
 * The random_password resources here serve two purposes:
 *   1. They generate the values during initial provisioning.
 *   2. They are then stored in Secrets Manager where the application
 *      reads them at runtime.
 *
 * For existing deployments, promote the Secrets Manager value to be
 * the authoritative source (import or set via the AWS console).
 */

# ── DB password ──────────────────────────────────────────────────────

resource "random_password" "db" {
  length           = 24
  special          = false
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db_password" {
  name        = "${var.app_name}-db-password-${var.environment}"
  description = "StockLens RDS PostgreSQL master password"
  # Force secret recreation if the random password changes
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.db_password != "" ? var.db_password : random_password.db.result
}

# ── JWT secret key ───────────────────────────────────────────────────

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "jwt_secret" {
  name                    = "${var.app_name}-jwt-secret-${var.environment}"
  description             = "StockLens JWT signing secret key"
  recovery_window_in_days = 7
}

# ── Full DATABASE_URL ─────────────────────────────────────────────

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.app_name}-database-url-${var.environment}"
  description             = "StockLens full DATABASE_URL with embedded password"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql+asyncpg://${var.app_name}:${var.db_password != "" ? var.db_password : random_password.db.result}@${aws_db_instance.main.endpoint}/${var.app_name}"
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = var.jwt_secret_key != "" ? var.jwt_secret_key : random_password.jwt.result
}

# ── Bedrock model ID ──────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "bedrock_model_id" {
  name                    = "${var.app_name}-bedrock-model-id-${var.environment}"
  description             = "StockLens Bedrock model ID"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "bedrock_model_id" {
  secret_id     = aws_secretsmanager_secret.bedrock_model_id.id
  secret_string = var.bedrock_model_id
}

# ── Redis AUTH password ──────────────────────────────────────────────────

resource "random_password" "redis" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "redis_pass" {
  name                    = "${var.app_name}-redis-pass-${var.environment}"
  description             = "StockLens ElastiCache Redis AUTH token"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "redis_pass" {
  secret_id     = aws_secretsmanager_secret.redis_pass.id
  secret_string = var.redis_pass != "" ? var.redis_pass : random_password.redis.result
}
