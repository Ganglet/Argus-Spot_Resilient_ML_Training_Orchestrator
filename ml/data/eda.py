import pandas as pd
import matplotlib.pyplot as plt
import os

if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "raw_spot_prices.csv")
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    subset = df[(df["instance_type"] == "m5.2xlarge") & (df["availability_zone"] == "eu-north-1c")].copy()
    subset = subset.set_index("timestamp").sort_index()

    # Identify smaller spikes since some instances don't jump as much
    subset['prev_price'] = subset['spot_price'].shift(1)
    subset['is_spike'] = (subset['spot_price'] > subset['prev_price'] * 1.01)
    spikes = subset[subset['is_spike']]

    plt.figure(figsize=(14, 5))
    plt.plot(subset.index, subset['spot_price'], label='Spot Price', color='#2ca02c')
    plt.scatter(spikes.index, spikes['spot_price'], color='red', s=50, label='Identified Spikes', zorder=5)
    plt.title("Spot Price Spike Patterns Identified (m5.2xlarge, eu-north-1c)")
    plt.ylabel("Price ($/hr)")
    plt.legend()
    plt.tight_layout()
    output_png = os.path.join(os.path.dirname(__file__), "eda_identified_spikes.png")
    plt.savefig(output_png)
    print(f"Identified {len(spikes)} significant price spikes.")

