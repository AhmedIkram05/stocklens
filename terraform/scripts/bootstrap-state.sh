#!/usr/bin/env bash
# One-time Terraform remote-state bootstrap (the bucket + lock table cannot
# use the remote backend themselves). Idempotent: safe to re-run.
# No manual clicks — fully scripted.
set -euo pipefail

REGION="${TF_STATE_REGION:-eu-west-2}"
BUCKET="${TF_STATE_BUCKET:-stocklens-tfstate}"

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || \
  aws s3 mb "s3://${BUCKET}" --region "$REGION"

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}'

echo "Remote state ready: s3://${BUCKET} (versioned+KMS, public access blocked)"
