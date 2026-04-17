import boto3
import pandas as pd
from datetime import datetime, timezone, timedelta
import time
import os

def fetch_spot_price_history(
    instance_types: list[str],
    region: str = "us-east-1",
    months: int = 6,
) -> pd.DataFrame:
    """
    Pull full Spot price history for the given instance types
    over the last `months` months, handling pagination automatically.
    """

    ec2 = boto3.client("ec2", region_name=region)

    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=30 * months)   # ~6 months back

    all_records = []

    paginator = ec2.get_paginator("describe_spot_price_history")

    page_iterator = paginator.paginate(
        InstanceTypes=instance_types,
        ProductDescriptions=["Linux/UNIX"],   # Filter to Linux only
        StartTime=start_time,
        EndTime=end_time,
    )

    print(f"Fetching Spot price history from {start_time.date()} to {end_time.date()} ...")

    for page_num, page in enumerate(page_iterator):
        records = page.get("SpotPriceHistory", [])
        all_records.extend(records)

        if page_num % 10 == 0:
            print(f"  Pages fetched: {page_num + 1} | Records so far: {len(all_records)}")

        time.sleep(0.1)   # Gentle rate limiting — avoid API throttling

    print(f"Total records fetched: {len(all_records)}")

    # Convert to DataFrame
    df = pd.DataFrame([
        {
            "timestamp":       r["Timestamp"],
            "instance_type":   r["InstanceType"],
            "availability_zone": r["AvailabilityZone"],
            "spot_price":      float(r["SpotPrice"]),
            "product_desc":    r["ProductDescription"],
        }
        for r in all_records
    ])

    if df.empty:
        print("WARNING: No records returned. Check instance types, region, or AWS credentials.")
        return df

    # Sort chronologically
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


if __name__ == "__main__":
    INSTANCE_TYPES = [
        "m5.xlarge", "m5.2xlarge",
        "c5.xlarge", "c5.2xlarge",
        "g4dn.xlarge",
    ]

    df = fetch_spot_price_history(
        instance_types=INSTANCE_TYPES,
        region="eu-north-1",
        months=6,
    )

    if not df.empty:
        print("\nSample data:")
        print(df.head(10))

        print("\nShape:", df.shape)
        print("Date range:", df["timestamp"].min(), "→", df["timestamp"].max())
        print("Instance types found:", df["instance_type"].unique())
        print("AZs found:", df["availability_zone"].unique())

        # Save raw data to CSV
        output_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(output_dir, "raw_spot_prices.csv")
        df.to_csv(output_path, index=False)
        print(f"\nSaved to {output_path}")
