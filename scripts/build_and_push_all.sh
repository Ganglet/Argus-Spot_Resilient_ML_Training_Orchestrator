#!/bin/bash
# Build and push all images to ECR for Week 6.
# Usage: bash scripts/build_and_push_all.sh [tag]
# Default tag: latest

set -e

TAG="${1:-latest}"

echo "=========================================="
echo "Building and pushing all images with tag: $TAG"
echo "=========================================="

echo ""
echo "1/3 Building predict-service..."
bash scripts/push_predict_service.sh "$TAG"

echo ""
echo "2/3 Building training-job..."
bash scripts/push_training_job.sh "$TAG"

echo ""
echo "3/3 Building operator..."
bash scripts/push_operator.sh "$TAG"

echo ""
echo "=========================================="
echo "All images built and pushed successfully!"
echo "=========================================="
