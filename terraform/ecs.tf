/**
 * ecs.tf
 * StockLens — ECS cluster, task definition, service, ALB, and target group.
 *
 * Architecture:
 *   Internet → ALB (port 80 / 443) → ECS Fargate tasks (port 8000)
 *
 * Manual steps after apply:
 *   1. Create an ACM certificate for your domain in eu-west-2.
 *   2. Add an HTTPS listener on the ALB (port 443) using that certificate.
 *   3. Point a Route53 A record (or alias) to the ALB DNS name.
 */

# ── CloudWatch log group ─────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.app_name}-${var.environment}"
  retention_in_days = 30
}

# ── ECS cluster ──────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.app_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ── ECS task definition ──────────────────────────────────────────────

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.app_name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  # Use ARM64 for cost-efficiency (Graviton-based Fargate)
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name  = "${var.app_name}"
      image = var.container_image

      essential = true

      # The container listens on 8000 (matches Dockerfile EXPOSE)
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
          appProtocol   = "http"
        }
      ]

      # ── Environment variables from Secrets Manager ──────────────
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_secretsmanager_secret.database_url.arn
        },
        {
          name      = "JWT_SECRET_KEY"
          valueFrom = aws_secretsmanager_secret.jwt_secret.arn
        }
      ]

      # ── Plain-text environment variables ────────────────────────
      environment = [
        {
          name  = "REDIS_URL"
          value = "redis://${aws_elasticache_replication_group.main.primary_endpoint_address}:${aws_elasticache_replication_group.main.port}/0"
        },
        {
          name  = "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
          value = "30"
        },
        {
          name  = "JWT_REFRESH_TOKEN_EXPIRE_DAYS"
          value = "7"
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "BEDROCK_MODEL_ID"
          value = var.bedrock_model_id
        },
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "STRUCTLOG_LOG_LEVEL"
          value = "INFO"
        },
        {
          name  = "RATE_LIMIT_LOGIN"
          value = "20/minute"
        },
        {
          name  = "RATE_LIMIT_DEFAULT"
          value = "100/minute"
        },
        {
          name  = "CORS_ORIGINS"
          value = join(",", var.cors_origins)
        }
      ]

      # ── Health check (must match ALB target group) ──────────────
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      # ── Logging to CloudWatch ───────────────────────────────────
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "${var.app_name}"
        }
      }
    }
  ])

  tags = {
    Name = "${var.app_name}-task-${var.environment}"
  }
}

# ── Application Load Balancer ────────────────────────────────────────

resource "aws_lb" "main" {
  name               = "${var.app_name}-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = local.public_subnet_ids
  ip_address_type    = "dualstack"

  enable_deletion_protection = true

  tags = {
    Name = "${var.app_name}-alb-${var.environment}"
  }
}

resource "aws_lb_target_group" "app" {
  name        = "${var.app_name}-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = local.vpc_id

  health_check {
    enabled             = true
    path                = "/health"
    port                = 8000
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = {
    Name = "${var.app_name}-tg-${var.environment}"
  }
}

# HTTP listener (placeholder — add HTTPS listener after ACM cert is ready)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# Once you have an ACM certificate, add an HTTPS listener:
# resource "aws_lb_listener" "https" {
#   load_balancer_arn = aws_lb.main.arn
#   port              = 443
#   protocol          = "HTTPS"
#   ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
#   certificate_arn   = "arn:aws:acm:eu-west-2:XXXXXXXXXXXX:certificate/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
#
#   default_action {
#     type             = "forward"
#     target_group_arn = aws_lb_target_group.app.arn
#   }
# }

# ── ECS service ──────────────────────────────────────────────────────

resource "aws_ecs_service" "main" {
  name            = "${var.app_name}-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Rolling deployment config
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Attach to ALB target group
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = var.app_name
    container_port   = 8000
  }

  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  # Enable ECS managed tags for cost allocation
  enable_ecs_managed_tags = true

  # Prevent accidental shutdown
  force_new_deployment = false

  depends_on = [
    aws_lb_listener.http,
    aws_db_instance.main,
    aws_elasticache_replication_group.main,
  ]

  tags = {
    Name = "${var.app_name}-service-${var.environment}"
  }
}
