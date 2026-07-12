/**
 * secrets/main.tf
 * StockLens — Secrets Manager secrets for sensitive configuration.
 *
 * The random_password resources serve two purposes:
 *   1. Generate values during initial provisioning.
 *   2. Store them in Secrets Manager where the application reads them.
 *
 * For existing deployments, promote the Secrets Manager value to be
 * the authoritative source.
 */

# ── DB password ──────────────────────────────────────────────────────

resource "random_password" "db" {
  length           = 24
  special          = false
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db_password" {
  # checkov:skip=CKV_AWS_149:dev — no KMS CMK; use default encryption
  # checkov:skip=CKV2_AWS_57:dev — secret rotation not configured; add Lambda in prod
  name                    = "${var.app_name}-db-password-${var.environment}"
  description             = "StockLens RDS PostgreSQL master password"
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
  # checkov:skip=CKV_AWS_149:dev — no KMS CMK; use default encryption
  # checkov:skip=CKV2_AWS_57:dev — secret rotation not configured; add Lambda in prod
  name                    = "${var.app_name}-jwt-secret-${var.environment}"
  description             = "StockLens JWT signing secret key"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = var.jwt_secret_key != "" ? var.jwt_secret_key : random_password.jwt.result
}

# ── Redis AUTH password ──────────────────────────────────────────────

resource "random_password" "redis" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "redis_pass" {
  # checkov:skip=CKV_AWS_149:dev — no KMS CMK; use default encryption
  # checkov:skip=CKV2_AWS_57:dev — secret rotation not configured; add Lambda in prod
  name                    = "${var.app_name}-redis-pass-${var.environment}"
  description             = "StockLens ElastiCache Redis AUTH token"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "redis_pass" {
  secret_id     = aws_secretsmanager_secret.redis_pass.id
  secret_string = var.redis_pass != "" ? var.redis_pass : random_password.redis.result
}
