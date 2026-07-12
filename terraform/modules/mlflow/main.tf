/**
 * mlflow/main.tf
 * StockLens — MLflow tracking server as a Fargate service (R3/R4).
 *
 * Runs the MLflow tracking server container on Fargate with an RDS
 * PostgreSQL backend store and S3 artifact root. Replaces the Phase 3/4
 * Docker Compose SQLite-backed MLflow instance.
 *
 * P3: RDS PostgreSQL store (retires SQLite)
 * P5: Scoped IAM role for S3 artifact upload
 * P6: CloudWatch logs via awslogs driver
 */

locals {
  family          = "${var.app_name}-mlflow-${var.environment}"
  mlflow_dns_name = "${aws_service_discovery_service.mlflow.name}.stocklens.internal"
}

# ── CloudWatch log group ─────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "mlflow" {
  # checkov:skip=CKV_AWS_158:dev — KMS key not provisioned yet
  name              = "/ecs/${local.family}"
  retention_in_days = 365
}

# ── ECS task definition ──────────────────────────────────────────────

resource "aws_ecs_task_definition" "mlflow" {
  family                   = local.family
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.mlflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "mlflow"
      image     = "ghcr.io/mlflow/mlflow:v2.20.3"
      essential = true
      command   = ["sh", "-c", "pip install -q psycopg2-binary && exec mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri ${var.mlflow_backend_store_uri} --default-artifact-root ${var.mlflow_artifact_root} --artifacts-destination ${var.mlflow_artifact_root}"]

      portMappings = [
        {
          containerPort = 5000
          hostPort      = 5000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "MLFLOW_BACKEND_STORE_URI"
          value = var.mlflow_backend_store_uri
        },
        {
          name  = "MLFLOW_DEFAULT_ARTIFACT_ROOT"
          value = var.mlflow_artifact_root
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "MLFLOW_S3_ENDPOINT_URL"
          value = "https://s3.${var.aws_region}.amazonaws.com"
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.mlflow.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "mlflow"
        }
      }
    }
  ])

  tags = {
    Name = local.family
  }
}

# ── ECS service ──────────────────────────────────────────────────────

# ── Cloud Map service discovery (R4 fix) ──────────────────────────────
# Registers the MLflow ECS service at mlflow.stocklens.internal:5000
# so Airflow can reach it via DNS without an NLB.

resource "aws_service_discovery_service" "mlflow" {
  name = "mlflow"

  dns_config {
    namespace_id = var.sd_namespace_id

    dns_records {
      ttl  = 60
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

resource "aws_ecs_service" "mlflow" {
  name            = local.family
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.mlflow.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    # checkov:skip=CKV_AWS_333:dev — no NAT gateway in dev VPC (ponytail)
    subnets         = var.private_subnet_ids
    security_groups = [var.mlflow_sg_id]
    # ponytail: dev — no NAT gateway, use public IPs
    assign_public_ip = true
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.mlflow.arn
    container_name = "mlflow"
  }

  enable_ecs_managed_tags = true
  force_new_deployment    = false

  tags = {
    Name = local.family
  }
}

# ── ECS task definition: mlflow db upgrade (one-off) ─────────────────
# Run once after initial RDS deployment to initialize the MLflow schema.
# Usage: aws ecs run-task --cluster <cluster> --task-definition mlflow-upgrade

resource "aws_ecs_task_definition" "mlflow_upgrade" {
  family                   = "${local.family}-upgrade"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.mlflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "mlflow-upgrade"
      image     = "ghcr.io/mlflow/mlflow:v2.20.3"
      essential = true
      command   = ["sh", "-c", "pip install -q psycopg2-binary && python3 -c \"import psycopg2; c = psycopg2.connect('${var.mlflow_backend_store_uri}'); c.cursor().execute('DROP TABLE IF EXISTS alembic_version'); c.commit(); c.close()\" && exec mlflow db upgrade ${var.mlflow_backend_store_uri}"]

      environment = [
        {
          name  = "MLFLOW_BACKEND_STORE_URI"
          value = var.mlflow_backend_store_uri
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.mlflow.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "mlflow-upgrade"
        }
      }
    }
  ])

  tags = {
    Name = "${local.family}-upgrade"
  }
}
