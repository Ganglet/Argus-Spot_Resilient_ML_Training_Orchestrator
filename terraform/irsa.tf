# ---------------------------------------------------------------------------
# IRSA (IAM Roles for Service Accounts)
# Lets K8s pods assume IAM roles without static credentials.
#
# Chain: EKS OIDC provider → IAM trust policy → K8s ServiceAccount annotation
#        → pod env var AWS_ROLE_ARN → AWS STS → temporary credentials
#
# This file depends on aws_eks_cluster.main from eks.tf.
# Apply eks.tf first, then this file.
# ---------------------------------------------------------------------------

# Tell AWS to trust the EKS cluster's OIDC provider
data "aws_iam_openid_connect_provider" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# ---------------------------------------------------------------------------
# Update the operator IAM role trust policy to use OIDC (replaces the
# placeholder ec2.amazonaws.com trust policy in iam.tf)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "operator_irsa" {
  name = "${var.project}-operator-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.eks.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub" = "system:serviceaccount:default:argus-operator"
          "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

# Attach same permissions as the original operator role
resource "aws_iam_role_policy" "operator_irsa" {
  name = "${var.project}-operator-irsa-policy"
  role = aws_iam_role.operator_irsa.id

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
