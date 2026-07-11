/**
 * network/main.tf
 * StockLens — Security groups and rules for all tiers.
 *
 * Using aws_security_group_rule resources (not inline rules)
 * for cleaner diffs and easier management.
 */

# ── ALB security group ───────────────────────────────────────────────

resource "aws_security_group" "alb" {
  name        = "${var.app_name}-alb-${var.environment}"
  description = "Controls access to the StockLens ALB"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "alb_ingress_http" {
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
