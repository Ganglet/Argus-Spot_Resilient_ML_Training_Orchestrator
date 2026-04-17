# ---------------------------------------------------------------------------
# Dead-letter queue — messages that fail processing land here for inspection
# ---------------------------------------------------------------------------
resource "aws_sqs_queue" "risk_events_dlq" {
  name                       = "${var.project}-risk-events-dlq"
  message_retention_seconds  = 1209600 # 14 days

  tags = { Name = "${var.project}-risk-events-dlq" }
}

# ---------------------------------------------------------------------------
# Main event queue — FastAPI prediction service publishes here;
# the K8s operator subscribes and triggers checkpoint + reschedule
#
# Message schema (agreed in docs/contracts.md):
# {
#   "job_name":           "cifar10-training",
#   "risk_score":         0.87,
#   "instance_type":      "m5.xlarge",
#   "az":                 "eu-north-1a",
#   "timestamp":          "2026-04-16T10:00:00Z",
#   "recommended_action": "checkpoint_and_migrate"
# }
# ---------------------------------------------------------------------------
resource "aws_sqs_queue" "risk_events" {
  name                       = "${var.project}-risk-events"
  visibility_timeout_seconds = 120   # operator must ack within 2 min
  message_retention_seconds  = 86400 # 1 day
  receive_wait_time_seconds  = 20    # long polling — reduces empty receives

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.risk_events_dlq.arn
    maxReceiveCount     = 3
  })

  tags = { Name = "${var.project}-risk-events" }
}

# Allow the operator's IAM role (defined in iam.tf) to send/receive/delete
resource "aws_sqs_queue_policy" "risk_events" {
  queue_url = aws_sqs_queue.risk_events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowArgusOperator"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.operator.arn }
        Action    = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource  = aws_sqs_queue.risk_events.arn
      }
    ]
  })
}
