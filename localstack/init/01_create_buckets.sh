#!/bin/bash
# Runs inside LocalStack on startup — creates the same buckets Terraform
# provisions in real AWS so local dev works without any Terraform apply.

set -e
ENDPOINT=http://localhost:4566
ACCOUNT_ID=000000000000   # LocalStack default fake account ID

echo "Creating LocalStack S3 buckets..."
awslocal s3api create-bucket \
  --bucket argus-checkpoints-${ACCOUNT_ID} \
  --create-bucket-configuration LocationConstraint=eu-north-1

awslocal s3api create-bucket \
  --bucket argus-feature-store-${ACCOUNT_ID} \
  --create-bucket-configuration LocationConstraint=eu-north-1

echo "Creating LocalStack SQS queues..."
awslocal sqs create-queue --queue-name argus-risk-events-dlq
awslocal sqs create-queue --queue-name argus-risk-events \
  --attributes '{"RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:eu-north-1:000000000000:argus-risk-events-dlq\",\"maxReceiveCount\":\"3\"}"}'

echo "LocalStack bootstrap complete."
