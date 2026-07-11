/**
 * airflow/main.tf
 * StockLens — Airflow webserver + scheduler as Fargate services (R3/R4).
 *
 * Runs Apache Airflow (LocalExecutor) as two Fargate services sharing an
 * RDS PostgreSQL metadata backend. The retraining DAG uses EcsRunTaskOperator
 * to invoke the ML training container.
 *
 * P1: VPC private subnets → RDS reachable
 * P3: RDS PostgreSQL metadata store (no SQLite)
 * P4: EcsRunTaskOperator for retraining
 * P5: Scoped IAM roles
 * P6: CloudWatch logging
 */

locals {
  family = "${var.app_name}-airflow-${var.environment}"
}

# ── CloudWatch log group ─────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "airflow" {
  name              = "/ecs/${local.family}"
  retention_in_days = 30
}

# ── Shared container definition (webserver + scheduler) ──────────────

locals {
  airflow_container = {
    name      = "airflow"
    image     = var.airflow_image
    essential = true

    environment = concat([
      {
        name  = "AIRFLOW__CORE__EXECUTOR"
        value = "LocalExecutor"
      },
      {
        name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"
        value = var.airflow_sql_alchemy_conn
      },
      {
        name  = "AIRFLOW__CORE__LOAD_EXAMPLES"
        value = "False"
      },
      {
        name  = "AIRFLOW__WEBSERVER__EXPOSE_CONFIG"
        value = "False"
      },
      {
        name  = "AWS_REGION"
        value = var.aws_region
      },
      {
        name  = "MLFLOW_TRACKING_URI"
        value = var.mlflow_tracking_uri
      },
      # Phase 4 DAG expects DATABASE_URL for direct asyncpg access
      {
        name  = "DATABASE_URL"
        value = var.airflow_sql_alchemy_conn
      },
    ], var.airflow_extra_env)

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.airflow.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "airflow"
      }
    }
  }
}

# ── ECS task definition (shared for webserver + scheduler) ───────────

resource "aws_ecs_task_definition" "airflow" {
  family                   = local.family
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.airflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([local.airflow_container])

  tags = {
    Name = local.family
  }
}

# ── Airflow webserver service ────────────────────────────────────────

resource "aws_ecs_service" "webserver" {
  name            = "${local.family}-webserver"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.airflow.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.airflow_sg_id]
    assign_public_ip = false
  }

  enable_ecs_managed_tags = true
  force_new_deployment    = false

  tags = {
    Name = "${local.family}-webserver"
  }
}

# ── Airflow scheduler service ────────────────────────────────────────

resource "aws_ecs_service" "scheduler" {
  name            = "${local.family}-scheduler"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.airflow.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.airflow_sg_id]
    assign_public_ip = false
  }

  enable_ecs_managed_tags = true
  force_new_deployment    = false

  tags = {
    Name = "${local.family}-scheduler"
  }
}

# ── ECS task definition: retraining trigger (P7) ─────────────────────
# Used by EventBridge rule to trigger airflow dags trigger weekly_retraining
# Closed-loop drift → auto-retrain via EcsRunTaskOperator.

resource "aws_ecs_task_definition" "trigger_retrain" {
  family                   = "${local.family}-trigger-retrain"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.airflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "trigger-retrain"
      image     = var.airflow_image
      essential = true
      command   = ["airflow", "dags", "trigger", "weekly_retraining"]

      environment = [
        {
          name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"
          value = var.airflow_sql_alchemy_conn
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.airflow.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "trigger-retrain"
        }
      }
    }
  ])

  tags = {
    Name = "${local.family}-trigger-retrain"
  }
}

# ── Closed-loop drift → auto-retrain (P7) ───────────────────────────
# EventBridge rule fires when the drift alarm enters ALARM state,
# triggering an ECS RunTask that runs `airflow dags trigger weekly_retraining`.

resource "aws_cloudwatch_event_rule" "drift_retrain" {
  count       = var.drift_alarm_name != "" ? 1 : 0
  name        = "${var.app_name}-drift-retrain-${var.environment}"
  description = "Trigger retraining DAG when drift alarm fires"

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      alarm-name = [var.drift_alarm_name]
      state = {
        value = ["ALARM"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "drift_retrain" {
  count     = var.drift_alarm_name != "" ? 1 : 0
  rule      = aws_cloudwatch_event_rule.drift_retrain[0].name
  target_id = "TriggerRetrain"
  arn       = var.ecs_cluster_arn
  role_arn  = var.eventbridge_ecs_role_arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.trigger_retrain.arn
    launch_type         = "FARGATE"
    network_configuration {
      assign_public_ip = false
      subnets          = var.private_subnet_ids
      security_groups  = [var.airflow_sg_id]
    }
  }
}
