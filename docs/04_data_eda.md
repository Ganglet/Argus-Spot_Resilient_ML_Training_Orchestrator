# Spot Price Data Exploration & Fetching

**Phase:** Week 1 — Data Exploration  
**Owner:** Person B  
**Status:** Complete — Scripts written and tested locally.

---

## Objective

Pull raw EC2 Spot price history from the S3 feature store and perform Exploratory Data Analysis (EDA) to understand price volatility, availability zone distributions, and patterns that precede an interruption.

---

## What Was Done

1. **`fetch_spot_prices.py`**: Created a script using `boto3` to connect to the AWS S3 feature store (`argus-feature-store-844641713781`). It downloads the raw generated CSVs containing timestamped price data.
2. **`eda.py`**: Developed an EDA pipeline using Pandas and Matplotlib to aggregate the Spot prices by instance type and Availability Zone.
3. **Visualization Generation**: Generated time-series plots to map out historical price spikes and drops over time.

---

## Commands

```bash
# Fetch the raw CSV data from the S3 feature store locally
python ml/data/fetch_spot_prices.py

# Generate exploratory time-series charts 
python ml/data/eda.py
```

---

## Why (Key Decisions)

**Why perform local EDA first?**  
Before feeding data into a deep learning model, we must understand the baseline volatility. Spot interruptions are often preceded by rapid price increases. By graphing `eda_price_series.png`, we can visually confirm these correlations to ensure our model has predictive power.

**Why skip committing the generated assets?**  
Assets like `eda_price_series.png` and raw downloaded `.csv` files change frequently and bloat the repository. They were strictly added to `.gitignore` to maintain repository health and prevent large Git history files.

---

## Outputs

| Output | Description |
|--------|-------------|
| `eda_price_series.png` | A local visualization mapping out Spot prices across `m5` and `c5` instances (ignored by Git). |
| `raw_spot_prices.csv` | Downloded raw dataset from S3 (ignored by Git). |
