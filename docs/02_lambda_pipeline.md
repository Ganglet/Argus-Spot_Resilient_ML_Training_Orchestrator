# Lambda Price Collector Pipeline

**Phase:** Week 2 — Data Pipeline  
**Owner:** Person A  
**Status:** Complete — Lambda live, writing CSVs to S3 every 5 minutes

---

## Objective

Build an automated pipeline that continuously collects EC2 Spot price history from the AWS pricing API and writes it to the S3 feature store. This is the raw data source for the entire ML prediction model.

---

## 1. Lambda Function (`argus-price-collector`)

**Runtime:** Python 3.11  
**Timeout:** 30s  
**Memory:** 256 MB  
**Source:** `lambda/price_collector/handler.py`

The function:
1. Calls `ec2.describe_spot_price_history()` for 6 target instance types, `Linux/UNIX` product
2. Pulls the last 10 minutes of prices (slight overlap with previous invocation to avoid gaps)
3. Writes a timestamped CSV to the feature store bucket

Target instance types:
```python
["m5.large", "m5.xlarge", "c5.large", "c5.xlarge", "t3.medium", "t3.large"]
```

These are the instance types the operator may schedule training jobs on — matching the prediction model's coverage to the operator's fallback list.

**Output path format:**
```
s3://argus-feature-store-844641713781/raw/YYYY/MM/DD/HH/prices_{timestamp}Z.csv
```

**CSV columns:** `timestamp`, `instance_type`, `az`, `spot_price`, `product`

---

## 2. EventBridge Rule (`argus-5min-cron`)

Triggers the Lambda every 5 minutes on a rate schedule:
```
schedule_expression = "rate(5 minutes)"
```

5-minute granularity matches the Spot price API's update frequency — finer than this returns duplicate records, coarser creates gaps in the time series.

---

## 3. CloudWatch Log Group

`/aws/lambda/argus-price-collector` — 7-day retention. Used to verify invocations and debug errors without incurring long-term log storage costs.

---

## Terraform Deployment

```bash
cd terraform/
terraform apply \
  -target=aws_lambda_function.price_collector \
  -target=aws_cloudwatch_event_rule.every_five_minutes \
  -target=aws_cloudwatch_event_target.trigger_lambda \
  -target=aws_lambda_permission.allow_eventbridge \
  -target=aws_cloudwatch_log_group.lambda_log
```

---

## Manual Test

```bash
# Invoke once manually
aws lambda invoke \
  --function-name argus-price-collector \
  --region eu-north-1 \
  /tmp/out.json && cat /tmp/out.json

# Confirm CSV appeared in S3
aws s3 ls s3://argus-feature-store-844641713781/raw/ --recursive --region eu-north-1
```

**Verified output:**
```
{"statusCode": 200, "body": "{\"records\": 18}"}
2026-04-18  raw/2026/04/17/19/prices_20260417T191404Z.csv
```

---

## Key Decisions

**Why Lambda + EventBridge instead of an EC2 cron job?**  
Lambda runs only when invoked — zero idle cost. An EC2 cron would cost ~$8/month just to exist. At 8,640 invocations/month (every 5 min × 24hr × 30 days), the Lambda stays well within the 1M free-tier requests.

**Why `FEATURE_STORE_BUCKET` env var instead of hardcoding?**  
The bucket name includes the account ID suffix. Using a Terraform output as an env var means the Lambda code never needs changing if the bucket is recreated.

**Why not use the AWS `AWS_REGION` env var?**  
`AWS_REGION` is a reserved Lambda environment variable — AWS sets it automatically to the deployment region. Attempting to override it throws `InvalidParameterCombination` on deploy.

**Why 10-minute lookback window instead of 5?**  
EventBridge has ±1 minute jitter on rate schedules. A 10-minute window guarantees overlap between consecutive invocations — no price records are missed at boundaries.

---

## Bug Fixed During Development

Person B's initial `lambda.tf` passed `BUCKET_NAME` as the env var name. `handler.py` reads `FEATURE_STORE_BUCKET`. This mismatch would have caused a `KeyError` crash on every Lambda invocation. Fixed before first deployment.
