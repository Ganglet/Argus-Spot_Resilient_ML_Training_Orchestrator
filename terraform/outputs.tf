output "checkpoint_bucket_name" {
  description = "S3 bucket for model checkpoints"
  value       = aws_s3_bucket.checkpoints.bucket
}

output "feature_store_bucket_name" {
  description = "S3 bucket for Spot price feature CSVs"
  value       = aws_s3_bucket.feature_store.bucket
}

output "risk_events_queue_url" {
  description = "SQS queue URL for risk event messages"
  value       = aws_sqs_queue.risk_events.url
}

output "risk_events_queue_arn" {
  description = "SQS queue ARN (needed for IAM policies)"
  value       = aws_sqs_queue.risk_events.arn
}

output "operator_role_arn" {
  description = "IAM role ARN for the K8s operator (used in IRSA Week 3)"
  value       = aws_iam_role.operator.arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs — used for EKS node groups"
  value       = [for s in aws_subnet.private : s.id]
}

output "public_subnet_ids" {
  description = "Public subnet IDs — used for load balancers"
  value       = [for s in aws_subnet.public : s.id]
}
