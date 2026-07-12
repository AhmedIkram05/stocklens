#!/usr/bin/env bash
# One-time Terraform remote-state bootstrap (the bucket + lock table cannot
# use the remote backend themselves). Idempotent: safe to re-run.
# No manual clicks — fully scripted.
set -euo pipefail

REGION="${TF_STATE_REGION:-eu-west-2}"
BUCKET="${TF_STATE_BUCKET:-stocklens-tfstate}"
TABLE="${TF_STATE_LOCK_TABLE:-stocklens-tfstate-lock}"

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || \
  aws s3 mb "s3://${BUCKET}" --region "$REGION"

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}'

aws dynamodb describe-table --table-name "$TABLE" >/dev/null 2>&1 || \
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --region "$REGION" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST

echo "Remote state ready: s3://${BUCKET} (versioned+KMS), table ${TABLE}"
