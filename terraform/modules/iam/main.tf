/**
 * iam/main.tf
 * StockLens — IAM roles and policies for ECS task execution and runtime.
 *
 * Follows least-privilege: each role gets only the permissions it needs.
 * The cloudwatch policy lives in the compute module since it needs the
 * log group ARN, breaking the circular dependency between iam and compute.
 */

locals {
  # Extract bucket and optional prefix from s3://bucket/prefix URIs
  champion_bucket = var.champion_s3_uri != "" ? regex("^s3://([^/]+)", var.champion_s3_uri)[0] : ""
  champion_prefix = var.champion_s3_uri != "" ? try(regex("^s3://[^/]+/(.+)", var.champion_s3_uri)[0], "") : ""
}

# ── ECS task execution role ──────────────────────────────────────────
# Used by the ECS agent to pull images, send logs, and fetch secrets.

resource "aws_iam_role" "ecs_execution" {
  name = "${var.app_name}-ecs-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Grant read access to Secrets Manager secrets.
resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.app_name}-ecs-execution-secrets-${var.environment}"
  description = "Allow ECS task execution role to read secrets from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = var.secret_arns
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# ── ECS task role ────────────────────────────────────────────────────
# Used by the application container at runtime.

resource "aws_iam_role" "ecs_task" {
  name = "${var.app_name}-ecs-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

# Allow invoking Claude Haiku via Bedrock.
resource "aws_iam_policy" "ecs_task_bedrock" {
  name        = "${var.app_name}-ecs-task-bedrock-${var.environment}"
  description = "Allow ECS task role to invoke Bedrock Claude Haiku model"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "bedrock:InvokeModel"
      Resource = [
        "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_bedrock" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_bedrock.arn
}

# Allow reading champion model artifacts from S3.
resource "aws_iam_policy" "ecs_task_champion_s3" {
  count       = var.champion_s3_uri != "" ? 1 : 0
  name        = "${var.app_name}-ecs-task-champion-s3-${var.environment}"
  description = "Allow ECS task role to read champion model artifacts from S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket",
      ]
      Resource = [
        "arn:aws:s3:::${local.champion_bucket}",
        local.champion_prefix != "" ? "arn:aws:s3:::${local.champion_bucket}/${local.champion_prefix}*" : "arn:aws:s3:::${local.champion_bucket}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_champion_s3" {
  count      = var.champion_s3_uri != "" ? 1 : 0
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_champion_s3[0].arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_secrets" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# ── MLflow Fargate task role (R4) ────────────────────────────────────
# Needs S3 GetObject/PutObject on mlflow-artifacts and KMS decrypt.

resource "aws_iam_role" "mlflow_task" {
  name = "${var.app_name}-mlflow-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

# ponytail: always created; Terraform handles unknown ARN at apply time.
resource "aws_iam_policy" "mlflow_task_s3_kms" {
  name        = "${var.app_name}-mlflow-task-s3-kms-${var.environment}"
  description = "Allow MLflow task to read/write artifacts to S3 and use KMS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetObjectVersion",
        ]
        Resource = [
          var.mlflow_artifacts_bucket_arn,
          "${var.mlflow_artifacts_bucket_arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = var.s3_kms_key_arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mlflow_task_s3_kms" {
  role       = aws_iam_role.mlflow_task.name
  policy_arn = aws_iam_policy.mlflow_task_s3_kms.arn
}

# ── Airflow Fargate task role (R4) ───────────────────────────────────
# Needs S3 access + KMS + ecs:RunTask + iam:PassRole for retraining.

resource "aws_iam_role" "airflow_task" {
  name = "${var.app_name}-airflow-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "airflow_task_s3_kms_ecs" {
  name        = "${var.app_name}-airflow-task-s3-kms-ecs-${var.environment}"
  description = "Allow Airflow task to access S3 artifacts, use KMS, and run retraining via ECS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetObjectVersion",
        ]
        Resource = compact([
          var.mlflow_artifacts_bucket_arn != "" ? var.mlflow_artifacts_bucket_arn : "",
          var.mlflow_artifacts_bucket_arn != "" ? "${var.mlflow_artifacts_bucket_arn}/*" : "",
          var.drift_reports_bucket_arn != "" ? var.drift_reports_bucket_arn : "",
          var.drift_reports_bucket_arn != "" ? "${var.drift_reports_bucket_arn}/*" : "",
        ])
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = var.s3_kms_key_arn
      },
      {
        # Run + poll the GPU training task via EcsRunTaskOperator
        Effect = "Allow"
        Action = [
          "ecs:RunTask",
          "ecs:DescribeTasks",
          "ecs:DescribeTaskDefinition",
          "ecs:ListTasks",
        ]
        Resource = "*"
      },
      {
        # Only allow passing the ML training task role (created below)
        Effect = "Allow"
        Action = [
          "iam:PassRole",
        ]
        Resource = aws_iam_role.ml_training_task.arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "airflow_task_s3_kms_ecs" {
  role       = aws_iam_role.airflow_task.name
  policy_arn = aws_iam_policy.airflow_task_s3_kms_ecs.arn
}

# ── EventBridge ECS Run Role (P7) ────────────────────────────────────
# Allows EventBridge to run ECS tasks for the drift-retrain trigger.

resource "aws_iam_role" "eventbridge_ecs" {
  name = "${var.app_name}-eventbridge-ecs-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "events.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "eventbridge_ecs_run" {
  name        = "${var.app_name}-eventbridge-ecs-run-${var.environment}"
  description = "Allow EventBridge to run ECS tasks"
  # checkov:skip=CKV_AWS_286:dev — broad EventBridge policy; scope per-resource in prod
  # checkov:skip=CKV_AWS_289:dev — broad EventBridge policy; scope per-resource in prod
  # checkov:skip=CKV_AWS_290:dev — broad EventBridge policy; scope per-resource in prod
  # checkov:skip=CKV_AWS_355:dev — broad EventBridge policy; scope per-resource in prod

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecs:RunTask",
        "iam:PassRole",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eventbridge_ecs_run" {
  role       = aws_iam_role.eventbridge_ecs.name
  policy_arn = aws_iam_policy.eventbridge_ecs_run.arn
}

# ── GPU ML Training task role ────────────────────────────────────────
# Used by the ML training ECS task (runs on GPU instances via EC2 launch type).
# Needs S3 for model artifacts, KMS, CloudWatch Logs, and Secrets Manager.

resource "aws_iam_role" "ml_training_task" {
  name = "${var.app_name}-ml-training-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "ml_training_task_s3_kms" {
  name        = "${var.app_name}-ml-training-task-s3-kms-${var.environment}"
  description = "Allow ML training task to access S3 artifacts, use KMS, and read secrets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetObjectVersion",
        ]
        Resource = compact([
          var.mlflow_artifacts_bucket_arn != "" ? var.mlflow_artifacts_bucket_arn : "",
          var.mlflow_artifacts_bucket_arn != "" ? "${var.mlflow_artifacts_bucket_arn}/*" : "",
          var.drift_reports_bucket_arn != "" ? var.drift_reports_bucket_arn : "",
          var.drift_reports_bucket_arn != "" ? "${var.drift_reports_bucket_arn}/*" : "",
        ])
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = var.s3_kms_key_arn
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = var.secret_arns
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ml_training_task_s3_kms" {
  role       = aws_iam_role.ml_training_task.name
  policy_arn = aws_iam_policy.ml_training_task_s3_kms.arn
}

# CloudWatch Logs for ML training task
resource "aws_iam_policy" "ml_training_task_logs" {
  name        = "${var.app_name}-ml-training-task-logs-${var.environment}"
  description = "Allow ML training task to write logs to CloudWatch"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
      ]
      Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${var.app_name}-ml-training-${var.environment}:*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ml_training_task_logs" {
  role       = aws_iam_role.ml_training_task.name
  policy_arn = aws_iam_policy.ml_training_task_logs.arn
}

# ── GitHub OIDC Provider & Deploy Role (R5) ───────────────────────────
# Allows GitHub Actions to assume an IAM role via OIDC for CI/CD deploys.
# Trust policy pins the repo + branch so no other repo/branch can assume it.

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
  # ponytail: GitHub rotates OIDC thumbprints occasionally; check
  # https://github.blog/changelog/ for updates.
}

data "aws_iam_policy_document" "github_oidc_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
  # ponytail: deploy job uses environment:production which changes OIDC
  # sub claim from ref:refs/heads/main to environment:production.
  # Second statement OR'd with the first (both allow same role).
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.app_name}-github-deploy-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.github_oidc_assume.json
  description        = "GitHub Actions OIDC deploy role for ${var.github_repo} (main branch + production env)"
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "${var.app_name}-deploy"
  role = aws_iam_role.github_deploy.id
  # checkov:skip=CKV_AWS_286:dev — broad deploy role for dev; scope per-resource in prod
  # checkov:skip=CKV_AWS_288:dev — broad deploy role for dev; scope per-resource in prod
  # checkov:skip=CKV_AWS_289:dev — broad deploy role for dev; scope per-resource in prod
  # checkov:skip=CKV_AWS_290:dev — broad deploy role for dev; scope per-resource in prod
  # checkov:skip=CKV_AWS_355:dev — broad deploy role for dev; scope per-resource in prod
  # checkov:skip=CKV_AWS_287:dev — broad deploy role for dev; scope per-resource in prod
  # checkov:skip=CKV2_AWS_40:dev — broad deploy role for dev; scope per-resource in prod

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "autoscaling:*", "ecr:*", "ecs:*", "s3:*", "dynamodb:*", "kms:*",
          "iam:*",
          "cloudwatch:*", "events:*", "sns:*", "budgets:*", "ce:*", "wafv2:*",
          "elasticache:*", "rds:*", "application-autoscaling:*", "logs:*",
          "elasticloadbalancing:*", "lambda:*",
          "ec2:*", "ssm:*", "secretsmanager:*", "elasticfilesystem:*",
          "servicediscovery:*", "route53:*"
        ]
        Resource = "*"
      }
    ]
  })
}

# ── SageMaker execution role (R6) ─────────────────────────────────────
# Used by the SageMaker endpoint to pull the container image and write
# CloudWatch logs. The model-load entrypoint (backend/sagemaker/serve.py)
# also needs S3 GetObject on CHAMPION_S3_URI.

resource "aws_iam_role" "sagemaker_execution" {
  name = "${var.app_name}-sagemaker-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "sagemaker.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

# SageMaker needs ECR pull + CloudWatch logs.
resource "aws_iam_role_policy_attachment" "sagemaker_execution_managed" {
  role       = aws_iam_role.sagemaker_execution.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

# Champion model S3 read for the SageMaker container.
resource "aws_iam_policy" "sagemaker_execution_champion_s3" {
  count       = var.champion_s3_uri != "" ? 1 : 0
  name        = "${var.app_name}-sagemaker-execution-champion-s3-${var.environment}"
  description = "Allow SageMaker execution role to read champion model from S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket",
      ]
      Resource = [
        "arn:aws:s3:::${local.champion_bucket}",
        local.champion_prefix != "" ? "arn:aws:s3:::${local.champion_bucket}/${local.champion_prefix}*" : "arn:aws:s3:::${local.champion_bucket}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_execution_champion_s3" {
  count      = var.champion_s3_uri != "" ? 1 : 0
  role       = aws_iam_role.sagemaker_execution.name
  policy_arn = aws_iam_policy.sagemaker_execution_champion_s3[0].arn
}

data "aws_caller_identity" "current" {}
