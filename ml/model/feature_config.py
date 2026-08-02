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
]
# Two features are computed by feature_pipeline.py but deliberately left out here -
# both scored WORSE on the held-out test set in single-run comparisons:
#   - "az_price_divergence": 0.0103 vs 0.0183 PR-AUC without it
#   - "instance_interruption_rate" (real AWS Spot Advisor data): 0.0172 vs 0.0211
# With only ~200 positive training examples, neither single comparison is strong
# evidence either feature is actually bad - both need a multi-seed comparison before
# being trusted. Don't add either back without re-running that comparison.

SEQ_LENGTH = 24  # 24 timesteps * 5 min = 2 hours of history
PREDICTION_HORIZON = 3  # predict interruption within the next 3 timesteps (15 min)
