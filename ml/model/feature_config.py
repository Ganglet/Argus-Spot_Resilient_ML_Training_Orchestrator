# Single source of truth for the feature contract between training and serving.
# dataset.py (training) and app.py (serving) both import from here so they can
# never drift apart on column set/order or sequence length again.

FEATURE_COLUMNS = [
    "spot_price", "price_delta",
    "rolling_mean_15m", "rolling_std_15m",
    "rolling_mean_1h", "rolling_std_1h",
    "rolling_mean_6h", "rolling_std_6h",
    "normalized_ratio",
    "sin_time_day", "cos_time_day",
    "sin_day_week", "cos_day_week",
    "instance_interruption_rate",
]
# "az_price_divergence" is computed by feature_pipeline.py but deliberately left out
# here: a single training run with it included scored WORSE on the held-out test set
# (PR-AUC 0.0103 vs 0.0183 without it). With only ~200 positive training examples,
# one run isn't strong evidence the feature is bad - it needs a multi-seed comparison
# before being trusted either way. Don't add it back without re-running that comparison.

SEQ_LENGTH = 24  # 24 timesteps * 5 min = 2 hours of history
PREDICTION_HORIZON = 3  # predict interruption within the next 3 timesteps (15 min)
