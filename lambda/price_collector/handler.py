"""
Lambda: Spot Price Collector
Runs every 5 minutes via EventBridge.
Pulls EC2 Spot price history for target instance types × AZs,
writes a timestamped CSV row to the S3 feature store.
"""
import csv
import io
import json
import os
from datetime import datetime, timezone, timedelta

import boto3

S3_BUCKET = os.environ["FEATURE_STORE_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")

# Instance types the Argus operator may schedule training jobs on
TARGET_INSTANCE_TYPES = [
    "m5.large", "m5.xlarge",
    "c5.large", "c5.xlarge",
    "t3.medium", "t3.large",
]

ec2 = boto3.client("ec2", region_name=AWS_REGION)
s3  = boto3.client("s3",  region_name=AWS_REGION)


def lambda_handler(event, context):
    now       = datetime.now(timezone.utc)
    since     = now - timedelta(minutes=10)   # slight overlap to avoid gaps
    date_key  = now.strftime("%Y/%m/%d")
    hour_key  = now.strftime("%H")
    s3_key    = f"raw/{date_key}/{hour_key}/prices_{now.strftime('%Y%m%dT%H%M%S')}Z.csv"

    rows = _fetch_spot_prices(since, now)
    if not rows:
        print("No price records returned — skipping write")
        return {"statusCode": 200, "body": "no_data"}

    csv_bytes = _to_csv(rows)
    s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=csv_bytes, ContentType="text/csv")

    print(json.dumps({"records": len(rows), "s3_key": s3_key}))
    return {"statusCode": 200, "body": json.dumps({"records": len(rows)})}


def _fetch_spot_prices(start: datetime, end: datetime) -> list[dict]:
    rows = []
    paginator = ec2.get_paginator("describe_spot_price_history")
    pages = paginator.paginate(
        InstanceTypes=TARGET_INSTANCE_TYPES,
        ProductDescriptions=["Linux/UNIX"],
        StartTime=start.isoformat(),
        EndTime=end.isoformat(),
    )
    for page in pages:
        for record in page["SpotPriceHistory"]:
            rows.append({
                "timestamp":     record["Timestamp"].isoformat(),
                "instance_type": record["InstanceType"],
                "az":            record["AvailabilityZone"],
                "spot_price":    record["SpotPrice"],
                "product":       record["ProductDescription"],
            })
    return rows


def _to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["timestamp", "instance_type", "az", "spot_price", "product"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")
