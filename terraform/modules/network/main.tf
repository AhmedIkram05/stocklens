/**
 * network/main.tf
 * StockLens — Security groups and rules for all tiers.
 *
 * Using aws_security_group_rule resources (not inline rules)
 * for cleaner diffs and easier management.
 */

# ── ALB security group ───────────────────────────────────────────────

resource "aws_security_group" "alb" {
  # checkov:skip=CKV2_AWS_5:dev — security group attached via variable reference; checkov can't trace
  name        = "${var.app_name}-alb-${var.environment}"
  description = "Controls access to the StockLens ALB"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "alb_ingress_http" {
  # checkov:skip=CKV_AWS_260:dev — public ALB needs port 80 from internet; add CloudFront + restrict in prod
  # tfsec:ignore:aws-ec2-no-public-ingress-sgr:dev — public ALB needs port 80 from internet
  security_group_id = aws_security_group.alb.id
  type              = "ingress"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "HTTP from anywhere"
}

# Uncomment after provisioning an ACM certificate in eu-west-2:
# resource "aws_security_group_rule" "alb_ingress_https" {
#   security_group_id = aws_security_group.alb.id
#   type              = "ingress"
#   from_port         = 443
#   to_port           = 443
#   protocol          = "tcp"
#   cidr_blocks       = ["0.0.0.0/0"]
#   description       = "HTTPS from anywhere"
# }

resource "aws_security_group_rule" "alb_egress_all" {
  # checkov:skip=CKV_AWS_382:dev — unrestricted egress for dev; scope per-service in prod
  # tfsec:ignore:aws-ec2-no-public-egress-sgr:dev — unrestricted egress for dev; scope per-service in prod
  security_group_id = aws_security_group.alb.id
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "All outbound traffic"
}

# ── ECS tasks security group ─────────────────────────────────────────

resource "aws_security_group" "ecs_tasks" {
  # checkov:skip=CKV2_AWS_5:dev — security group attached via variable reference; checkov can't trace
  name        = "${var.app_name}-ecs-tasks-${var.environment}"
  description = "Controls access to StockLens ECS tasks"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "ecs_tasks_ingress_alb" {
  security_group_id        = aws_security_group.ecs_tasks.id
  type                     = "ingress"
  from_port                = 8000
  to_port                  = 8000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Allow traffic from ALB on port 8000"
}

resource "aws_security_group_rule" "ecs_tasks_egress_all" {
  # checkov:skip=CKV_AWS_382:dev — unrestricted egress for dev; scope per-service in prod
  # tfsec:ignore:aws-ec2-no-public-egress-sgr:dev — unrestricted egress for dev; scope per-service in prod
  security_group_id = aws_security_group.ecs_tasks.id
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "All outbound traffic"
}

# ── RDS security group ───────────────────────────────────────────────

resource "aws_security_group" "rds" {
  # checkov:skip=CKV2_AWS_5:dev — security group attached via variable reference; checkov can't trace
  name        = "${var.app_name}-rds-${var.environment}"
  description = "Controls access to StockLens RDS PostgreSQL"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "rds_ingress_ecs" {
  security_group_id        = aws_security_group.rds.id
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Allow PostgreSQL from ECS tasks"
}

# ── ElastiCache Redis security group ─────────────────────────────────

resource "aws_security_group" "redis" {
  # checkov:skip=CKV2_AWS_5:dev — security group attached via variable reference; checkov can't trace
  name        = "${var.app_name}-redis-${var.environment}"
  description = "Controls access to StockLens ElastiCache Redis"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "redis_ingress_ecs" {
  security_group_id        = aws_security_group.redis.id
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Allow Redis from ECS tasks"
}

# ── MLflow security group (R4) ────────────────────────────────────────

resource "aws_security_group" "mlflow" {
  # checkov:skip=CKV2_AWS_5:dev — security group attached via variable reference; checkov can't trace
  name        = "${var.app_name}-mlflow-${var.environment}"
  description = "Controls access to StockLens MLflow tracking server"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "mlflow_ingress_mlflow_tcp" {
  security_group_id = aws_security_group.mlflow.id
  type              = "ingress"
  from_port         = 5000
  to_port           = 5000
  protocol          = "tcp"
  self              = true
  description       = "Allow MLflow port 5000 within the MLflow SG"
}

resource "aws_security_group_rule" "mlflow_ingress_rds" {
  security_group_id        = aws_security_group.rds.id
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.mlflow.id
  description              = "Allow PostgreSQL from MLflow tasks"
}

resource "aws_security_group_rule" "mlflow_egress_all" {
  # checkov:skip=CKV_AWS_382:dev — unrestricted egress for dev; scope per-service in prod
  # tfsec:ignore:aws-ec2-no-public-egress-sgr:dev — unrestricted egress for dev; scope per-service in prod
  security_group_id = aws_security_group.mlflow.id
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "All outbound traffic"
}

# ── Airflow security group (R4) ──────────────────────────────────────

resource "aws_security_group" "airflow" {
  # checkov:skip=CKV2_AWS_5:dev — security group attached via variable reference; checkov can't trace
  name        = "${var.app_name}-airflow-${var.environment}"
  description = "Controls access to StockLens Airflow services"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "airflow_ingress_rds" {
  security_group_id        = aws_security_group.rds.id
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.airflow.id
  description              = "Allow PostgreSQL from Airflow tasks"
}

resource "aws_security_group_rule" "airflow_egress_all" {
  # checkov:skip=CKV_AWS_382:dev — unrestricted egress for dev; scope per-service in prod
  # tfsec:ignore:aws-ec2-no-public-egress-sgr:dev — unrestricted egress for dev; scope per-service in prod
  security_group_id = aws_security_group.airflow.id
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "All outbound traffic"
}

# ── MLflow ingress from Airflow (R4 fix) ──────────────────────────────
# Allows Airflow tasks to reach the MLflow tracking server on port 5000
# via Service Discovery DNS.

resource "aws_security_group_rule" "mlflow_ingress_airflow" {
  security_group_id        = aws_security_group.mlflow.id
  type                     = "ingress"
  from_port                = 5000
  to_port                  = 5000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.airflow.id
  description              = "Allow Airflow to reach MLflow tracking server port 5000"
}

# ── Cloud Map private DNS namespace (R4 fix) ──────────────────────────
# Used by MLflow ECS service for DNS-based service discovery.

resource "aws_service_discovery_private_dns_namespace" "stocklens" {
  name        = "stocklens.internal"
  description = "Private DNS namespace for StockLens service discovery"
  vpc         = var.vpc_id
}
