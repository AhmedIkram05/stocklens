/**
 * locals.tf
 * StockLens — local values for VPC/subnet fallback logic.
 *
 * When vpc_id / subnet_ids are provided via variables, those are used.
 * When omitted, the VPC module creates them and the module outputs are
 * referenced instead.
 */
locals {
  # Use var.vpc_id as the single guard: if provided, all network vars
  # come from variables. If empty, VPC module (count=1) provides them.
  vpc_id             = var.vpc_id != "" ? var.vpc_id : module.vpc[0].vpc_id
  private_subnet_ids = var.vpc_id != "" ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  public_subnet_ids  = var.vpc_id != "" ? var.public_subnet_ids : module.vpc[0].public_subnet_ids

  # Champion S3 ARN — extracted from s3://bucket/prefix/ → arn:aws:s3:::bucket/prefix/*
  # Used by the ECS task role policy for champion model delivery.
  champion_bucket     = try(regex("^s3://([^/]+)", var.champion_s3_uri)[0], "")
  champion_prefix     = try(regex("^s3://[^/]+/(.*)", var.champion_s3_uri)[0], "")
  champion_bucket_arn = local.champion_bucket != "" ? "arn:aws:s3:::${local.champion_bucket}" : ""
  champion_prefix_arn = local.champion_bucket_arn != "" ? "${local.champion_bucket_arn}/${local.champion_prefix}*" : ""

  # R4: MLflow / Airflow connection strings
  mlflow_db_uri = "postgresql://${module.database.db_username}:${module.secrets.db_password_value}@${module.database.db_address}:5432/${module.database.db_name}"

  airflow_db_uri = "postgresql+psycopg2://${module.database.db_username}:${module.secrets.db_password_value}@${module.database.db_address}:5432/${module.database.db_name}"

  mlflow_artifact_root = "s3://${module.s3.mlflow_artifacts_bucket_name}/mlflow/"
}
