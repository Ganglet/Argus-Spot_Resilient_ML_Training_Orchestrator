# ---------------------------------------------------------------------------
# Lambda Function - Fetches Spot Prices Every 5 Min
# ---------------------------------------------------------------------------

data "archive_file" "price_collector_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/price_collector"
  output_path = "${path.module}/price_collector.zip"
}

resource "aws_lambda_function" "price_collector" {
  filename         = data.archive_file.price_collector_zip.output_path
  function_name    = "${var.project}-price-collector"
  role             = aws_iam_role.lambda_price_collector.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.price_collector_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.feature_store.id
      REGION      = var.aws_region
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda_log" {
  name              = "/aws/lambda/${aws_lambda_function.price_collector.function_name}"
  retention_in_days = 7
}

# ---------------------------------------------------------------------------
# EventBridge Rule - Trigger Lambda every 5 minutes
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "every_five_minutes" {
  name                = "${var.project}-5min-cron"
  description         = "Fires every 5 minutes to trigger the price collector"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "trigger_lambda" {
  rule      = aws_cloudwatch_event_rule.every_five_minutes.name
  target_id = "TriggerLambda"
  arn       = aws_lambda_function.price_collector.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.price_collector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_five_minutes.arn
}