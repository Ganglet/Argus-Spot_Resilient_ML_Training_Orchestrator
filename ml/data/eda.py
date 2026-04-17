import pandas as pd
import matplotlib.pyplot as plt
import os

if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "raw_spot_prices.csv")
    if not os.path.exists(csv_path):
        print(f"Error: Could not find {csv_path}. Run fetch_spot_prices.py first.")
        exit(1)

    df = pd.read_csv(csv_path, parse_dates=["timestamp"])

    # Check for gaps
    print("Record count by instance type and AZ:")
    print(df.groupby(["instance_type", "availability_zone"]).size())

    # Plot price series for one instance type
    # First, let's find the first instance type + AZ pair that has data
    if not df.empty:
        first_row = df.iloc[0]
        instance_type = first_row["instance_type"]
        az = first_row["availability_zone"]

        subset = df[
            (df["instance_type"] == instance_type) &
            (df["availability_zone"] == az)
        ].set_index("timestamp")

        if not subset.empty:
            subset["spot_price"].plot(figsize=(14, 4), title=f"{instance_type} Spot Price - {az}")
            plt.ylabel("Price ($/hr)")
            plt.tight_layout()
            
            output_png = os.path.join(os.path.dirname(__file__), "eda_price_series.png")
            plt.savefig(output_png)
            print(f"Saved plot to {output_png}")
            plt.show()
