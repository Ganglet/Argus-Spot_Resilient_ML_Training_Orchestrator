import pandas as pd
import numpy as np
import os

# Approximate On-Demand prices for your eu-north-1 region (in USD/hr)
# The ML model uses this to understand if Spot is currently cheap or expensive relatively.
OD_PRICES = {
    "m5.xlarge": 0.204,
    "m5.2xlarge": 0.408,
    "c5.xlarge": 0.188,
    "c5.2xlarge": 0.376,
    "g4dn.xlarge": 0.605,
}

def process_ts_group(group: pd.DataFrame) -> pd.DataFrame:
    """
    Takes raw spot prices for a specific instance type + AZ, 
    resamples them to fixed 5-minute intervals, and engineers features.
    """
    instance_type = group["instance_type"].iloc[0]
    az = group["availability_zone"].iloc[0]
    
    # Needs to be sorted by time
    group = group.sort_values("timestamp").set_index("timestamp")
    
    # 1. Resample to strict 5-minute intervals (Spot prices are event-driven, 
    # but Transformers need fixed timesteps). Forward-fill missing intervals.
    group = group.resample("5min").ffill()
    group = group.bfill() # Just in case the first row was NaN
    
    # Ensure categorical data is persisted after resample
    group["instance_type"] = instance_type
    group["availability_zone"] = az
    
    # 2. Price delta (change between consecutive 5-min samples)
    group["price_delta"] = group["spot_price"].diff().fillna(0)
    
    # 3. Rolling stats (15-min=3 steps, 1-hr=12 steps, 6-hr=72 steps)
    group["rolling_mean_15m"] = group["spot_price"].rolling(window=3, min_periods=1).mean()
    group["rolling_std_15m"]  = group["spot_price"].rolling(window=3, min_periods=1).std().fillna(0)
    
    group["rolling_mean_1h"]  = group["spot_price"].rolling(window=12, min_periods=1).mean()
    group["rolling_std_1h"]   = group["spot_price"].rolling(window=12, min_periods=1).std().fillna(0)
    
    group["rolling_mean_6h"]  = group["spot_price"].rolling(window=72, min_periods=1).mean()
    group["rolling_std_6h"]   = group["spot_price"].rolling(window=72, min_periods=1).std().fillna(0)
    
    # 4. Normalized ratio relative to On-Demand price
    od_price = OD_PRICES.get(instance_type, 1.0)
    group["normalized_ratio"] = group["spot_price"] / od_price
    
    # 5. Temporal encodings (Cyclical time features using Sine/Cosine)
    # Time of day
    sec_in_day = 24 * 60 * 60
    time_seconds = group.index.hour * 3600 + group.index.minute * 60 + group.index.second
    group["sin_time_day"] = np.sin(2 * np.pi * time_seconds / sec_in_day)
    group["cos_time_day"] = np.cos(2 * np.pi * time_seconds / sec_in_day)
    
    # Day of week (0-6)
    group["sin_day_week"] = np.sin(2 * np.pi * group.index.dayofweek / 7)
    group["cos_day_week"] = np.cos(2 * np.pi * group.index.dayofweek / 7)
    
    return group.reset_index()

def build_features(input_csv: str, output_csv: str):
    print(f"Loading raw data from {input_csv}...")
    df = pd.read_csv(input_csv, parse_dates=["timestamp"])
    
    print("Generating feature matrix...")
    processed_groups = []
    
    # Process each instance type and AZ individually so their time series don't mix
    for (itype, az), group in df.groupby(["instance_type", "availability_zone"]):
        processed_df = process_ts_group(group)
        processed_groups.append(processed_df)
        
    final_df = pd.concat(processed_groups, ignore_index=True)
    
    # Drop rows where we don't have enough data (just clean up)
    final_df = final_df.dropna()
    
    print(f"Shape of engineered feature dataset: {final_df.shape}")
    print("\nSample engineered features:")
    print(final_df[["timestamp", "spot_price", "price_delta", "rolling_mean_1h", "normalized_ratio", "sin_time_day"]].head())
    
    final_df.to_csv(output_csv, index=False)
    print(f"\nSaved engineered features to {output_csv}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    in_path = os.path.join(base_dir, "raw_spot_prices.csv")
    out_path = os.path.join(base_dir, "features.csv")
    
    if not os.path.exists(in_path):
        print(f"Error: {in_path} not found. Run fetch_spot_prices.py first.")
        exit(1)
        
    build_features(in_path, out_path)