#!/bin/bash
# Build and push the ML training Docker image to ECR.
# Usage: ./build-and-push.sh [tag]
#   tag defaults to ml-training-latest
set -euo pipefail

AWS_ACCOUNT="327936092014"
AWS_REGION="eu-west-2"
REPO_NAME="stocklens-dev"
TAG="${1:-ml-training-latest}"
IMAGE_URI="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO_NAME}:${TAG}"

echo "=== Logging into ECR ==="
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "=== Building ML training image ==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
docker build -f "${SCRIPT_DIR}/Dockerfile" -t "${REPO_NAME}:${TAG}" "${SCRIPT_DIR}"

echo "=== Tagging and pushing ==="
docker tag "${REPO_NAME}:${TAG}" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

echo "=== Done: ${IMAGE_URI} ==="
