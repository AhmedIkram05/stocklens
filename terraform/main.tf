/**
 * main.tf
 * StockLens — Terraform configuration, provider setup, and module roots.
 *
 * Manual pre-requisites before first apply:
 *   1. Run scripts/bootstrap-state.sh <env> <region> to create S3 backend.
 *   2. An ACM certificate for the domain (add HTTPS listener once ready).
 *   3. A hosted zone in Route53 (or external DNS) pointed at the ALB.
 *
 * VPC and subnets are created by the VPC module unless existing IDs are
 * supplied via variables.
 */

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # ── Remote state ──
  # Run scripts/bootstrap-state.sh <env> <region> before first apply.
  # Values hardcoded — bootstrap script always creates these names.
  # Change manually if you use a different env/region.
  backend "s3" {
    bucket       = "stocklens-tfstate"
    key          = "stocklens/production/terraform.tfstate"
    region       = "eu-west-2"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Name        = var.app_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── VPC ──────────────────────────────────────────────────────────────

module "vpc" {
  source             = "./modules/vpc"
  environment        = var.environment
  app_name           = var.app_name
  availability_zones = var.availability_zones
  count              = var.vpc_id == "" ? 1 : 0
}

# ── Network (security groups) ────────────────────────────────────────

module "network" {
  source      = "./modules/network"
  vpc_id      = local.vpc_id
  app_name    = var.app_name
  environment = var.environment
}

# ── Secrets ──────────────────────────────────────────────────────────

module "secrets" {
  source         = "./modules/secrets"
  app_name       = var.app_name
  environment    = var.environment
  db_password    = var.db_password
  jwt_secret_key = var.jwt_secret_key
  redis_pass     = var.redis_pass
}

# ── S3 ───────────────────────────────────────────────────────────────

module "s3" {
  source      = "./modules/s3"
  environment = var.environment
  app_name    = var.app_name
}

# ── Database ─────────────────────────────────────────────────────────

module "database" {
  source             = "./modules/database"
  vpc_id             = local.vpc_id
  private_subnet_ids = local.private_subnet_ids
  rds_sg_id          = module.network.rds_sg_id
  db_password        = module.secrets.db_password_value
  app_name           = var.app_name
  environment        = var.environment
  db_instance_class  = var.db_instance_class
  db_storage_gb      = var.db_storage_gb
  db_max_storage_gb  = var.db_max_storage_gb
}

# ── Cache ────────────────────────────────────────────────────────────

module "cache" {
  source             = "./modules/cache"
  vpc_id             = local.vpc_id
  private_subnet_ids = local.private_subnet_ids
  redis_sg_id        = module.network.redis_sg_id
  redis_pass         = module.secrets.redis_pass_value
  app_name           = var.app_name
  environment        = var.environment
  redis_node_type    = var.redis_node_type
}

# ── IAM ──────────────────────────────────────────────────────────────

module "iam" {
  source      = "./modules/iam"
  app_name    = var.app_name
  environment = var.environment
  aws_region  = var.aws_region
  secret_arns = [
    module.secrets.db_password_secret_arn,
    module.secrets.jwt_secret_arn,
    module.secrets.redis_pass_secret_arn,
    module.database.db_secret_arn,
  ]
  champion_s3_uri             = var.champion_s3_uri
  mlflow_artifacts_bucket_arn = module.s3.mlflow_artifacts_bucket_arn
  drift_reports_bucket_arn    = module.s3.drift_reports_bucket_arn
  s3_kms_key_arn              = module.s3.s3_kms_key_arn
  github_repo                 = var.github_repo
}

# ── Compute ──────────────────────────────────────────────────────────

module "compute" {
  source                  = "./modules/compute"
  app_name                = var.app_name
  environment             = var.environment
  aws_region              = var.aws_region
  vpc_id                  = local.vpc_id
  public_subnet_ids       = local.public_subnet_ids
  private_subnet_ids      = local.private_subnet_ids
  alb_sg_id               = module.network.alb_sg_id
  ecs_tasks_sg_id         = module.network.ecs_tasks_sg_id
  ecs_execution_role_arn  = module.iam.ecs_execution_role_arn
  ecs_task_role_arn       = module.iam.ecs_task_role_arn
  ecs_task_role_name      = module.iam.ecs_task_role_name
  container_image         = var.container_image
  cors_origins            = var.cors_origins
  ecs_cpu                 = var.ecs_cpu
  ecs_memory              = var.ecs_memory
  desired_count           = var.desired_count
  redis_endpoint          = module.cache.redis_endpoint
  redis_port              = module.cache.redis_port
  database_url_secret_arn = module.database.db_secret_arn
  jwt_secret_arn          = module.secrets.jwt_secret_arn
  redis_pass_secret_arn   = module.secrets.redis_pass_secret_arn
  champion_s3_uri         = var.champion_s3_uri
  s3_kms_key_arn          = module.s3.s3_kms_key_arn
  ecs_min_capacity        = var.ecs_min_capacity
  ecs_max_capacity        = var.ecs_max_capacity
  ecs_cpu_target          = var.ecs_cpu_target
  ecs_rps_target          = var.ecs_rps_target
  key_name                = var.key_name
}

# ── MLflow tracking server (R4) ─────────────────────────────────────

module "mlflow" {
  source                   = "./modules/mlflow"
  app_name                 = var.app_name
  environment              = var.environment
  aws_region               = var.aws_region
  ecs_cluster_id           = module.compute.ecs_cluster_id
  ecs_execution_role_arn   = module.iam.ecs_execution_role_arn
  mlflow_task_role_arn     = module.iam.mlflow_task_role_arn
  private_subnet_ids       = local.private_subnet_ids
  mlflow_sg_id             = module.network.mlflow_sg_id
  mlflow_backend_store_uri = local.mlflow_db_uri
  mlflow_artifact_root     = local.mlflow_artifact_root
  sd_namespace_id          = module.network.sd_namespace_id
}

# ── Airflow (R4) ─────────────────────────────────────────────────────

module "airflow" {
  source                    = "./modules/airflow"
  app_name                  = var.app_name
  environment               = var.environment
  aws_region                = var.aws_region
  ecs_cluster_id            = module.compute.ecs_cluster_id
  ecs_execution_role_arn    = module.iam.ecs_execution_role_arn
  airflow_task_role_arn     = module.iam.airflow_task_role_arn
  airflow_sg_id             = module.network.airflow_sg_id
  private_subnet_ids        = local.private_subnet_ids
  airflow_sql_alchemy_conn  = local.airflow_db_uri
  mlflow_tracking_uri       = module.mlflow.mlflow_tracking_uri
  drift_alarm_name          = module.monitoring.drift_alarm_name
  ecs_cluster_arn           = module.compute.ecs_cluster_arn
  eventbridge_ecs_role_arn  = module.iam.eventbridge_ecs_role_arn
  airflow_image             = var.airflow_image
  ml_training_task_role_arn = module.iam.ml_training_task_role_arn
  ml_training_image         = var.ml_training_image
  efs_filesystem_id         = local.efs_filesystem_id
  ecs_cluster_name          = module.compute.ecs_cluster_name
  database_url              = local.database_url
  jwt_secret_arn            = module.secrets.jwt_secret_arn
}

# ── WAF ──────────────────────────────────────────────────────────────

module "waf" {
  source            = "./modules/waf"
  env               = var.environment
  alb_arn           = module.compute.alb_arn
  rate_limit        = var.environment == "production" ? 2000 : 5000
  rate_limit_action = "block"
}

# ── Monitoring ───────────────────────────────────────────────────────

module "monitoring" {
  source             = "./modules/monitoring"
  env                = var.environment
  alert_email        = var.alert_email
  ecs_cluster_name   = module.compute.ecs_cluster_name
  ecs_service_name   = module.compute.ecs_service_name
  alb_name_suffix    = module.compute.alb_name
  rds_instance_id    = module.database.db_instance_id
  ecs_log_group_name = module.compute.log_group_name
}

# ── SageMaker (R6) ────────────────────────────────────────────────────

module "sagemaker" {
  source                              = "./modules/sagemaker"
  app_name                            = var.app_name
  environment                         = var.environment
  aws_region                          = var.aws_region
  container_image                     = var.sagemaker_image
  champion_s3_uri                     = var.champion_s3_uri
  sagemaker_execution_role_arn        = module.iam.sagemaker_execution_role_arn
  sagemaker_instance_type             = var.sagemaker_instance_type
  sagemaker_model_download_timeout    = var.sagemaker_model_download_timeout
  sagemaker_container_startup_timeout = var.sagemaker_container_startup_timeout
}

# ── Budgets ──────────────────────────────────────────────────────────

module "budgets" {
  source               = "./modules/budgets"
  environment          = var.environment
  budget_monthly_limit = var.budget_monthly_limit
  budget_sns_arns      = [module.monitoring.sns_topic_arn]
  budget_sns_arn       = module.monitoring.sns_topic_arn
}

# ── R6: SageMaker InvokeEndpoint permission ───────────────────────────
# Created outside any module to avoid a circular dependency:
#   IAM module → needs endpoint ARN  →  SageMaker module → needs execution role ARN
# By placing the policy in the root module, both outputs are available.

resource "aws_iam_policy" "ecs_task_sagemaker_invoke" {
  name        = "${var.app_name}-ecs-task-sagemaker-invoke-${var.environment}"
  description = "Allow ECS task role to invoke SageMaker prediction endpoint"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sagemaker:InvokeEndpoint",
      ]
      Resource = module.sagemaker.sagemaker_endpoint_arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_sagemaker_invoke" {
  role       = module.iam.ecs_task_role_name
  policy_arn = aws_iam_policy.ecs_task_sagemaker_invoke.arn
}
