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

  # Airflow variables passed via environment
  airflow_variables = {
    ecs_cluster_name = var.ecs_cluster_name
    # ponytail: derived internally — no circular dependency needed
    ml_training_task_definition = "${local.family}-ml-training"
    private_subnet_ids          = join(",", var.private_subnet_ids)
    airflow_sg_id               = var.airflow_sg_id
    database_url                = var.database_url
    mlflow_tracking_uri         = var.mlflow_tracking_uri
    app_name                    = var.app_name
    environment                 = var.environment
    aws_region                  = var.aws_region
  }
}

# ── CloudWatch log group ─────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "airflow" {
  # checkov:skip=CKV_AWS_158:dev — KMS key not provisioned yet
  # tfsec:ignore:aws-cloudwatch-log-group-encrypted:dev — KMS key not provisioned yet
  name              = "/ecs/${local.family}"
  retention_in_days = 365
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
      # DAG Discovery & Parsing Fixes (critical for DAG detection)
      {
        name  = "AIRFLOW__CORE__DAG_DISCOVERY_SAFE_MODE"
        value = "False"
      },
      {
        name  = "AIRFLOW__CORE__DAGBAG_IMPORT_TIMEOUT"
        value = "300"
      },
      {
        name  = "AIRFLOW__CORE__DAG_FILE_PROCESSOR_TIMEOUT"
        value = "300"
      },
      # Critical Airflow Core & Scheduler Configuration
      {
        name  = "AIRFLOW__CORE__DAGS_FOLDER"
        value = "/opt/airflow/dags"
      },
      {
        name  = "AIRFLOW__SCHEDULER__MIN_FILE_PROCESS_INTERVAL"
        value = "30"
      },
      {
        name  = "AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL"
        value = "300"
      },
      {
        name  = "AIRFLOW__SCHEDULER__PARSING_PROCESSES"
        value = "2"
      },
      # Standalone DAG processor (Airflow 3.x — required for DAG parsing)
      {
        name  = "AIRFLOW__SCHEDULER__STANDALONE_DAG_PROCESSOR"
        value = "True"
      },
      # Database connection pooling for stability
      {
        name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_POOL_ENABLED"
        value = "True"
      },
      {
        name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_POOL_SIZE"
        value = "10"
      },
      {
        name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_POOL_RECYCLE"
        value = "1800"
      },
      {
        name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_POOL_PRE_PING"
        value = "True"
      },
      {
        name  = "AIRFLOW__DATABASE__SQL_ALCHEMY_POOL_TIMEOUT"
        value = "30"
      },
      {
        name  = "AIRFLOW__CORE__ENABLE_XCOM_PICKLING"
        value = "True"
      },
      {
        name  = "AIRFLOW__SCHEDULER__SCHEDULER_HEARTBEAT_SEC"
        value = "10"
      },
      {
        name  = "AIRFLOW__SCHEDULER__DAG_RUN_TIMEOUT"
        value = "3600"
      },

      {
        name  = "AWS_REGION"
        value = var.aws_region
      },
      {
        name  = "MLFLOW_TRACKING_URI"
        value = var.mlflow_tracking_uri
      },
      # DAG's asyncpg helpers read DATABASE_URL directly; must be postgresql:// (not +psycopg2)
      {
        name  = "DATABASE_URL"
        value = var.database_url
      },
      # BaseHook.get_connection("postgres_default") used by DAG's _check_new_ohlcv_data, _cleanup
      {
        name  = "AIRFLOW_CONN_POSTGRES_DEFAULT"
        value = var.database_url
      },
      # Airflow Variables for EcsRunTaskOperator (prefixed with AIRFLOW_VAR_)
      {
        name  = "AIRFLOW_VAR_ECS_CLUSTER_NAME"
        value = local.airflow_variables.ecs_cluster_name
      },
      {
        name  = "AIRFLOW_VAR_ML_TRAINING_TASK_DEFINITION"
        value = local.airflow_variables.ml_training_task_definition
      },
      {
        name  = "AIRFLOW_VAR_PRIVATE_SUBNET_IDS"
        value = local.airflow_variables.private_subnet_ids
      },
      {
        name  = "AIRFLOW_VAR_AIRFLOW_SG_ID"
        value = local.airflow_variables.airflow_sg_id
      },
      {
        name  = "AIRFLOW_VAR_DATABASE_URL"
        value = local.airflow_variables.database_url
      },
      {
        name  = "AIRFLOW_VAR_MLFLOW_TRACKING_URI"
        value = local.airflow_variables.mlflow_tracking_uri
      },
      {
        name  = "AIRFLOW_VAR_APP_NAME"
        value = local.airflow_variables.app_name
      },
      {
        name  = "AIRFLOW_VAR_ENVIRONMENT"
        value = local.airflow_variables.environment
      },
      {
        name  = "AIRFLOW_VAR_AWS_REGION"
        value = local.airflow_variables.aws_region
      },
    ], var.airflow_extra_env)

    # ponytail: JWT_SECRET_KEY needed because alembic's env.py imports src.config.Settings
    # which validates ALL pydantic fields on instantiation, not just DATABASE_URL.
    secrets = [
      {
        name      = "JWT_SECRET_KEY"
        valueFrom = var.jwt_secret_arn
      },
    ]

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

# ── ECS task definitions (one per command) ────────────────────────────

resource "aws_ecs_task_definition" "webserver" {
  family                   = "${local.family}-webserver"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.airflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([merge(
    local.airflow_container,
    # ponytail: PYTHONPATH=/app needed so alembic can import src.config from /app/src
    { entryPoint = ["sh", "-c"], command = ["cd /app && PYTHONPATH=/app alembic upgrade head && python3 /opt/airflow/scripts/drop_alembic_version.py && airflow db migrate && exec airflow api-server"] }

  )])

  tags = {
    Name = "${local.family}-webserver"
  }
}

resource "aws_ecs_task_definition" "scheduler" {
  family                   = "${local.family}-scheduler"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.airflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([merge(
    local.airflow_container,
    # ponytail: PYTHONPATH=/app needed so alembic can import src.config from /app/src
    { entryPoint = ["sh", "-c"], command = ["cd /app && PYTHONPATH=/app alembic upgrade head && python3 /opt/airflow/scripts/drop_alembic_version.py && airflow db migrate && (airflow dag-processor &) && exec airflow scheduler"] }
  )])

  tags = {
    Name = "${local.family}-scheduler"
  }
}

# ── Airflow webserver service ────────────────────────────────────────

resource "aws_ecs_service" "webserver" {
  name            = "${local.family}-webserver"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.webserver.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    # checkov:skip=CKV_AWS_333:dev — no NAT gateway in dev VPC (ponytail)
    subnets         = var.private_subnet_ids
    security_groups = [var.airflow_sg_id]
    # ponytail: dev — no NAT gateway
    assign_public_ip = true
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
  task_definition = aws_ecs_task_definition.scheduler.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    # checkov:skip=CKV_AWS_333:dev — no NAT gateway in dev VPC (ponytail)
    subnets         = var.private_subnet_ids
    security_groups = [var.airflow_sg_id]
    # ponytail: dev — no NAT gateway
    assign_public_ip = true
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
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.airflow_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name       = "trigger-retrain"
      image      = var.airflow_image
      essential  = true
      entryPoint = ["sh", "-c"]
      command    = ["airflow dags trigger weekly_retraining"]

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
      # ponytail: dev — no NAT gateway
      assign_public_ip = true
      subnets          = var.private_subnet_ids
      security_groups  = [var.airflow_sg_id]
    }
  }
}

# ── ECS task definition: GPU ML Training (for EcsRunTaskOperator) ─────
# Runs on EC2 GPU instances (g5.xlarge) via ECS EC2 launch type or
# Fargate Spot with GPU (when available). Requires x86_64 architecture.
# The task is launched by the Airflow DAG via EcsRunTaskOperator.

resource "aws_ecs_task_definition" "ml_training" {
  count        = var.ml_training_image != "" && var.ml_training_task_role_arn != "" ? 1 : 0
  family       = "${local.family}-ml-training"
  network_mode = "awsvpc"
  # GPU ML training runs on EC2 (g5.xlarge) — Fargate does not support GPU workloads.
  requires_compatibilities = ["EC2"]
  cpu                      = "4096"  # 4 vCPU
  memory                   = "16384" # 16 GB
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ml_training_task_role_arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name       = "ml-training"
      image      = var.ml_training_image
      essential  = true
      entryPoint = ["sh", "-c"]
      command    = ["python -m ml.pipeline"]

      environment = [
        {
          name  = "DATABASE_URL"
          value = var.airflow_sql_alchemy_conn
        },
        {
          name  = "MLFLOW_TRACKING_URI"
          value = var.mlflow_tracking_uri
        },
        {
          name  = "MODEL_ARTIFACT_DIR"
          value = "/model_artifacts/champion"
        },
        {
          name  = "MLFLOW_ARTIFACT_ROOT"
          value = "/mlflow/artifacts"
        },
        {
          name  = "MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING"
          value = "true"
        },
        {
          name  = "ENVIRONMENT"
          value = var.environment
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
          "awslogs-stream-prefix" = "ml-training"
        }
      }

      resourceRequirements = [
        {
          type  = "GPU"
          value = "1"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "model_artifacts"
          containerPath = "/model_artifacts"
          readOnly      = false
        },
        {
          sourceVolume  = "mlflow_data"
          containerPath = "/mlflow"
          readOnly      = false
        }
      ]
    }
  ])

  volume {
    name = "model_artifacts"
    efs_volume_configuration {
      file_system_id          = var.efs_filesystem_id
      root_directory          = "/model_artifacts"
      transit_encryption      = "ENABLED"
      transit_encryption_port = 2999
    }
  }

  volume {
    name = "mlflow_data"
    efs_volume_configuration {
      file_system_id          = var.efs_filesystem_id
      root_directory          = "/mlflow"
      transit_encryption      = "ENABLED"
      transit_encryption_port = 2998
    }
  }

  tags = {
    Name = "${local.family}-ml-training"
  }
}
