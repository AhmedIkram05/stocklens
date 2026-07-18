/**
 * compute/main.tf
 * StockLens — ECS cluster, task definition, service, ALB, target group,
 * listener, CloudWatch log group, and ECR repository.
 *
 * Architecture:
 *   Internet → ALB (port 80) → ECS Fargate tasks (port 8000)
 *
 * Also creates the CloudWatch log policy for the ECS task role, since
 * it needs the log group ARN (breaks the circular dependency between
 * the iam and compute modules).
 */

# ── CloudWatch log group ─────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "app" {
  # checkov:skip=CKV_AWS_158:dev — KMS key not provisioned yet
  # tfsec:ignore:aws-cloudwatch-log-group-customer-key:dev — KMS key not provisioned yet
  name              = "/ecs/${var.app_name}-${var.environment}"
  retention_in_days = 365
}

# Allow writing application logs to CloudWatch.
resource "aws_iam_policy" "ecs_task_cloudwatch" {
  name        = "${var.app_name}-ecs-task-cloudwatch-${var.environment}"
  description = "Allow ECS task role to send logs to CloudWatch Logs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
      ]
      Resource = "${aws_cloudwatch_log_group.app.arn}:*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_cloudwatch" {
  role       = var.ecs_task_role_name
  policy_arn = aws_iam_policy.ecs_task_cloudwatch.arn
}

# ── ECR repository ───────────────────────────────────────────────────

resource "aws_ecr_repository" "app" {
  # checkov:skip=CKV_AWS_51:dev — mutable tags for fast iteration (ponytail)
  # checkov:skip=CKV_AWS_136:dev — KMS key not provisioned yet for ECR encryption
  # tfsec:ignore:aws-ecr-enforce-immutable-repository:dev — mutable tags for fast iteration
  # tfsec:ignore:aws-ecr-repository-customer-key:dev — KMS key not provisioned yet
  name = "${var.app_name}-${var.environment}"
  # ponytail: dev — mutable tags for fast iteration
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

# ── ECS cluster ──────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.app_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ── GPU EC2 Launch Template (g5.xlarge for ML training) ──────────────
# The ml_training task runs on EC2 GPU instances via this capacity provider.

data "aws_ssm_parameter" "ecs_agent_installed_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

resource "aws_launch_template" "ml_training_gpu" {
  name          = "${var.app_name}-ml-training-gpu-${var.environment}"
  image_id      = data.aws_ssm_parameter.ecs_agent_installed_ami.value
  instance_type = "g5.xlarge"

  # IAM instance profile for EC2 -> must have ECS agent + secrets access
  iam_instance_profile {
    name = aws_iam_instance_profile.ecs_gpu.name
  }

  key_name = var.key_name

  network_interfaces {
    associate_public_ip_address = false
    device_index                = 0
    security_groups             = [var.ecs_tasks_sg_id]
  }

  user_data = base64encode(<<-EOF
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.main.name}" >> /etc/ecs/ecs.config
    echo "ECS_GPU_ENABLED=true" >> /etc/ecs/ecs.config
EOF
  )

  ebs_optimized = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.app_name}-ml-training-gpu-${var.environment}"
    }
  }
}

# IAM instance profile for GPU EC2 instances (no additional perms needed beyond what task roles grant)
locals {
  # Extract the role name from the ARN (arn:aws:iam::account:role/name -> name)
  ecs_execution_role_name = var.ecs_execution_role_arn != "" ? split("/", var.ecs_execution_role_arn)[1] : ""
}

resource "aws_iam_instance_profile" "ecs_gpu" {
  name = "${var.app_name}-ecs-gpu-${var.environment}"
  role = local.ecs_execution_role_name
}

# EC2 capacity provider for GPU instances (g5.xlarge)
resource "aws_ecs_capacity_provider" "ml_training_gpu" {
  name = "${var.app_name}-gpu-${var.environment}"

  auto_scaling_group_provider {
    auto_scaling_group_arn = aws_autoscaling_group.ml_training_gpu.arn
    managed_scaling {
      status                    = "ENABLED"
      maximum_scaling_step_size = 5
      minimum_scaling_step_size = 1
      target_capacity           = 1
    }
    managed_termination_protection = "DISABLED"
  }
}

# Auto Scaling Group for GPU instances — single g5.xlarge always-on for ML training
resource "aws_autoscaling_group" "ml_training_gpu" {
  name                      = "${var.app_name}-ml-training-gpu-${var.environment}"
  min_size                  = 0
  max_size                  = 4
  desired_capacity          = 0 # Starts at 0; scales up when ML training task launches
  vpc_zone_identifier       = var.private_subnet_ids
  health_check_type         = "ELB"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.ml_training_gpu.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.app_name}-ml-training-gpu-${var.environment}"
    propagate_at_launch = true
  }

  tag {
    key                 = "ECS_CLUSTER"
    value               = aws_ecs_cluster.main.name
    propagate_at_launch = true
  }

  # ponytail: hardcode name to break circular dependency with capacity_provider resource
  tag {
    key                 = "ECS_CAPACITY_PROVIDER"
    value               = "${var.app_name}-gpu-${var.environment}"
    propagate_at_launch = true
  }

  lifecycle {
    # Scale in only when no running tasks — handled by ECS managed scaling
    # ponytail: start at 0 capacity, let managed scaling handle it
  }
}

# Attach GPU capacity provider to the ECS cluster
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", aws_ecs_capacity_provider.ml_training_gpu.name]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }

  depends_on = [aws_autoscaling_group.ml_training_gpu]
}

# ── Application Load Balancer ────────────────────────────────────────

data "aws_elb_service_account" "main" {}

resource "aws_s3_bucket" "alb_logs" {
  # checkov:skip=CKV_AWS_18:dev — access logging on the access-log bucket is circular
  # checkov:skip=CKV2_AWS_62:dev — no event notifications needed for ALB logs
  # checkov:skip=CKV_AWS_144:dev — single region, no cross-replication needed
  # checkov:skip=CKV_AWS_21:dev — access logs bucket, versioning not critical
  # checkov:skip=CKV_AWS_145:dev — S3 AES256 encryption sufficient for access logs
  # tfsec:ignore:aws-s3-enable-bucket-encryption:dev — AES256 sufficient for access logs
  # tfsec:ignore:aws-s3-encryption-customer-key:dev — AES256 sufficient for access logs
  # tfsec:ignore:aws-s3-enable-bucket-logging:dev — access logging on access-log bucket is circular
  # tfsec:ignore:aws-s3-enable-versioning:dev — versioning not critical for access logs
  bucket = "${var.app_name}-alb-logs-${var.environment}"
}

resource "aws_s3_bucket_ownership_controls" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        AWS = data.aws_elb_service_account.main.arn
      }
      Action   = "s3:PutObject"
      Resource = "${aws_s3_bucket.alb_logs.arn}/alb-logs/*"
    }]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket                  = aws_s3_bucket.alb_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_lb" "main" {
  # checkov:skip=CKV2_AWS_28:dev — WAF associated via module variable; checkov can't trace
  # tfsec:ignore:aws-elb-alb-not-public:dev — public ALB required for internet-facing app
  name     = "${var.app_name}-${var.environment}"
  internal = false
  # checkov:skip=CKV2_AWS_20:dev — no ACM cert; use HTTPS listener + redirect in prod
  # tfsec:ignore:aws-elb-http-not-used:dev — HTTP listener for dev; HTTPS in prod
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnet_ids
  ip_address_type    = "ipv4"

  access_logs {
    bucket  = aws_s3_bucket.alb_logs.id
    prefix  = "alb-logs"
    enabled = true
  }

  drop_invalid_header_fields = true
  enable_deletion_protection = true

  tags = {
    Name = "${var.app_name}-alb-${var.environment}"
  }
}

resource "aws_lb_target_group" "app" {
  # checkov:skip=CKV_AWS_378:dev — HTTP target group for dev; use HTTPS in prod
  # tfsec:ignore:aws-elb-http-not-used:dev — HTTP target group for dev; HTTPS in prod
  name        = "${var.app_name}-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

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
  # checkov:skip=CKV_AWS_2:dev — no ACM cert; add HTTPS listener + redirect in prod
  # checkov:skip=CKV2_AWS_20:dev — no ACM cert; add HTTPS redirect in prod
  # checkov:skip=CKV_AWS_103:dev — no ACM cert; use TLS 1.2 in prod
  # tfsec:ignore:aws-elb-http-not-used:dev — HTTP listener for dev; HTTPS in prod
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# ── ECS task definition ──────────────────────────────────────────────

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.app_name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn
  # tfsec:ignore:aws-ecs-no-plaintext-secrets:dev — JWT_* env vars are config durations, not secrets
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = var.app_name
      image     = var.container_image
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
          appProtocol   = "http"
        }
      ]

      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = var.database_url_secret_arn
        },
        {
          name      = "JWT_SECRET_KEY"
          valueFrom = var.jwt_secret_arn
        },
        {
          name      = "REDIS_PASSWORD"
          valueFrom = var.redis_pass_secret_arn
        },
        {
          name      = "LANGCHAIN_API_KEY"
          valueFrom = var.langsmith_api_key_secret_arn
        }
      ]

      environment = [
        {
          name  = "REDIS_HOST"
          value = var.redis_endpoint
        },
        {
          name  = "REDIS_PORT"
          value = tostring(var.redis_port)
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
        },
        {
          name  = "CHAMPION_S3_URI"
          value = var.champion_s3_uri
        },
        {
          name  = "BEDROCK_MODEL_ID"
          value = "anthropic.claude-haiku-4-5-20251001-v1:0"
        },
        {
          name  = "LANGCHAIN_TRACING_V2"
          value = "true"
        },
        {
          name  = "LANGCHAIN_PROJECT"
          value = "stocklens-${var.environment}"
        }
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = var.app_name
        }
      }
    }
  ])

  tags = {
    Name = "${var.app_name}-task-${var.environment}"
  }
}

# ── ECS service ──────────────────────────────────────────────────────

resource "aws_ecs_service" "main" {
  name            = "${var.app_name}-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = var.app_name
    container_port   = 8000
  }

  network_configuration {
    # checkov:skip=CKV_AWS_333:dev — no NAT gateway in dev VPC (ponytail)
    subnets         = var.private_subnet_ids
    security_groups = [var.ecs_tasks_sg_id]
    # ponytail: dev — public IPs needed since subnets have no NAT gateway.
    # Switch to false + NAT GW or VPC endpoint for Secrets Manager in prod.
    assign_public_ip = true
  }

  enable_ecs_managed_tags = true
  force_new_deployment    = false

  # Automatic rollback on failed health check (R5)
  deployment_controller {
    type = "ECS"
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [
    aws_lb_listener.http,
  ]

  tags = {
    Name = "${var.app_name}-service-${var.environment}"
  }
}

# ── Auto Scaling (R3) ──────────────────────────────────────────────────
# Target-tracking scaling on CPU utilisation and request count per target.

resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.ecs_max_capacity
  min_capacity       = var.ecs_min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.main.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.app_name}-cpu-target-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = var.ecs_cpu_target
  }
}

resource "aws_appautoscaling_policy" "ecs_rps" {
  name               = "${var.app_name}-rps-target-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      # format: app/<alb-name>/<alb-id>/targetgroup/<tg-name>/<tg-id>
      resource_label = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.app.arn_suffix}"
    }
    target_value     = var.ecs_rps_target
    disable_scale_in = false
  }
}

# ── EFS filesystem for model artifacts and MLflow data ────────────────

resource "aws_efs_file_system" "model_artifacts" {
  creation_token = "${var.app_name}-${var.environment}-model-artifacts"

  encrypted  = true
  kms_key_id = var.s3_kms_key_arn

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name = "${var.app_name}-model-artifacts-${var.environment}"
  }
}

resource "aws_efs_mount_target" "model_artifacts" {
  count = length(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.model_artifacts.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [var.ecs_tasks_sg_id]
}
