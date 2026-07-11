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
