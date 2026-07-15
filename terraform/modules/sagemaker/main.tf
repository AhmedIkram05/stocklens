/**
 * sagemaker/main.tf
 * StockLens — SageMaker model, endpoint configuration (serverless),
 * and endpoint for the prediction inference container.
 *
 * The SageMaker endpoint is an alternate serving path for predictions.
 * When PREDICTION_SERVING_BACKEND=sagemaker on the Fargate task, the
 * ECS container calls InvokeEndpoint instead of running the model locally.
 *
 * The SageMaker model points to the same Container image used by the
 * ECS task, but with a different entrypoint: the sagemaker/serve.py
 * handler instead of the FastAPI server.
 */

data "aws_caller_identity" "current" {}

data "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id = "stocklens-jwt-secret-${var.environment}"
}

# ── SageMaker model ───────────────────────────────────────────────────
# Reuses the same ECR image as the ECS Fargate task, but overrides
# the entrypoint to the SageMaker serving handler (backend/sagemaker/serve.py).

resource "aws_sagemaker_model" "prediction" {
  name                     = "${var.app_name}-prediction-model-${var.environment}"
  enable_network_isolation = true

  primary_container {
    image = var.container_image
    # ponytail: SageMaker entrypoint override;
    # inference.py directly imports the existing backend code.
    # Upgrade to SageMaker PyTorch Toolkit when throughput demands it.
    container_hostname = "${var.app_name}-prediction"
    # ponytail: construct tar.gz path from prefix — SageMaker model_data_url requires a tar.gz
    model_data_url     = "${var.champion_s3_uri}/model.tar.gz"

    environment = {
      ENVIRONMENT            = var.environment
      AWS_REGION             = var.aws_region
      CHAMPION_S3_URI        = var.champion_s3_uri
      SAGEMAKER_SERVING_PORT = "8080"
      JWT_SECRET_KEY         = data.aws_secretsmanager_secret_version.jwt_secret.secret_string
    }
  }

  execution_role_arn = var.sagemaker_execution_role_arn

  tags = {
    Name        = "${var.app_name}-prediction-model"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── KMS key for SageMaker endpoint encryption at rest ──────────────────
# Dedicated key so the SageMaker service never falls back to AWS-managed.
# ponytail: single-region key; cross-region replication not needed.

resource "aws_kms_key" "sagemaker" {
  description             = "KMS key for SageMaker endpoint encryption at rest"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "EnableRootAccess"
      Effect = "Allow"
      Principal = {
        AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
      }
      Action   = "kms:*"
      Resource = "*"
    }]
  })
  tags = {
    Name        = "${var.app_name}-sagemaker-endpoint"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "sagemaker" {
  name          = "alias/${var.app_name}-sagemaker-endpoint-${var.environment}"
  target_key_id = aws_kms_key.sagemaker.key_id
}

# ── Provisioned endpoint configuration ─────────────────────────────────
# Provisioned Inference: configurable timeouts solve cold-start SLA.
# Serverless 4-min health check timeout was non-configurable.

resource "aws_sagemaker_endpoint_configuration" "prediction" {
  name = "${var.app_name}-prediction-endpoint-config-${var.environment}"

  kms_key_arn = aws_kms_key.sagemaker.arn

  production_variants {
    variant_name           = "primary"
    model_name             = aws_sagemaker_model.prediction.name
    initial_instance_count = 1
    instance_type          = var.sagemaker_instance_type

    # Configurable timeouts (seconds) — solves the cold-start SLA
    model_data_download_timeout_in_seconds         = var.sagemaker_model_download_timeout
    container_startup_health_check_timeout_in_seconds = var.sagemaker_container_startup_timeout
  }

  tags = {
    Name        = "${var.app_name}-prediction-endpoint-config"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── SageMaker endpoint ────────────────────────────────────────────────
# Production endpoint that the Fargate task calls via InvokeEndpoint.

resource "aws_sagemaker_endpoint" "prediction" {
  name                 = "${var.app_name}-prediction-production-${var.environment}"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.prediction.name

  tags = {
    Name        = "${var.app_name}-prediction-endpoint"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
