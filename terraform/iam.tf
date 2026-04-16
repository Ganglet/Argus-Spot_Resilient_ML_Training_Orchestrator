# ---------------------------------------------------------------------------
# Lambda execution role — allows the price collector Lambda to write to S3
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_price_collector" {
  name = "${var.project}-lambda-price-collector"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_price_collector" {
  name = "${var.project}-lambda-price-collector-policy"
  role = aws_iam_role.lambda_price_collector.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Write Spot price CSVs to the feature store bucket
        Sid      = "WriteFeatureStore"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.feature_store.arn}/raw/*"
      },
      {
        # Describe Spot price history
        Sid      = "DescribeSpotPrices"
        Effect   = "Allow"
        Action   = ["ec2:DescribeSpotPriceHistory"]
        Resource = "*"
      },
      {
        # CloudWatch Logs
        Sid    = "Logs"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Argus Operator IAM role
# This role is attached to the K8s operator pod via IRSA (Week 3).
# Declared here so sqs.tf can reference its ARN in the queue policy.
# The OIDC trust policy is added in Week 3 when EKS is live.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "operator" {
  name = "${var.project}-operator"

  # Placeholder assume-role policy — replaced with OIDC trust in Week 3
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "operator" {
  name = "${var.project}-operator-policy"
  role = aws_iam_role.operator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Checkpoints"
        Effect = "Allow"
        Action = [
          "s3:PutObject", "s3:GetObject", "s3:ListBucket",
          "s3:CreateMultipartUpload", "s3:UploadPart", "s3:CompleteMultipartUpload"
        ]
        Resource = [
          aws_s3_bucket.checkpoints.arn,
          "${aws_s3_bucket.checkpoints.arn}/*"
        ]
      },
      {
        Sid    = "RiskEventQueue"
        Effect = "Allow"
        Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.risk_events.arn
      }
    ]
  })
}
