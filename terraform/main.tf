/**
 * main.tf
 * StockLens — Terraform configuration, provider setup, and module roots.
 *
 * Manual pre-requisites before first apply:
 *   1. An ACM certificate for the domain (add HTTPS listener once ready).
 *   2. A hosted zone in Route53 (or external DNS) pointed at the ALB.
 *
 * VPC and subnets are created by the VPC module unless existing IDs are
 * supplied via variables.
 */

terraform {
  required_version = ">= 1.6"

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

  # ════════════════════════════════════════════════════════════════════
  # ⚠️  CRITICAL: Local state only! Before any production apply:
  #     1. Create S3 bucket + DynamoDB table for state locking
  #     2. Uncomment this backend block
  #     3. Run `terraform init -migrate` to migrate state
  #
  #     Without remote state, losing this machine = losing all
  #     infrastructure management capability.
  # ════════════════════════════════════════════════════════════════════
  # backend "s3" {
  #   bucket         = "stocklens-terraform-state"
  #   key            = "production/terraform.tfstate"
  #   region         = "eu-west-2"
  #   dynamodb_table = "stocklens-terraform-locks"
  #   encrypt        = true
  # }
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

module "vpc" {
  source             = "./modules/vpc"
  environment        = var.environment
  app_name           = var.app_name
  availability_zones = var.availability_zones
  count              = var.vpc_id == "" ? 1 : 0
}

module "s3" {
  source      = "./modules/s3"
  environment = var.environment
  app_name    = var.app_name
}
