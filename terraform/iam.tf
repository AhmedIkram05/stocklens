/**
 * iam.tf
 * StockLens — IAM roles and policies for ECS task execution and runtime.
 *
 * Follows least-privilege: each role gets only the permissions it needs.
 */

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

# Grant read access to the two Secrets Manager secrets we created.
resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.app_name}-ecs-execution-secrets-${var.environment}"
  description = "Allow ECS task execution role to read DB password and JWT secret from Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = [
        aws_secretsmanager_secret.db_password.arn,
        aws_secretsmanager_secret.jwt_secret.arn,
        aws_secretsmanager_secret.database_url.arn,
        aws_secretsmanager_secret.bedrock_model_id.arn,
        aws_secretsmanager_secret.redis_pass.arn,
      ]
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
        "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_bedrock" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_bedrock.arn
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
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_cloudwatch.arn
}
