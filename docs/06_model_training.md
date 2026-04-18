# Transformer Model & MLflow Tracking

**Phase:** Week 3 — Model Training  
**Owner:** Person B  
**Status:** Complete — Model trained, tracked via MLflow, and optimized locally.

---

## Objective

Train a Transformer-based deep learning model to predict the probability of an EC2 Spot interruption based on the feature engineering pipeline. Track all experiments, hyperparameter tuning, and losses efficiently using MLflow.

---

## What Was Done

1. **`transformer.py`**: Built a PyTorch TransformerEncoder architecture capable of processing the time-series sequences derived from the Feature Pipeline.
2. **`train.py` & Focal Loss**: Implemented the main training loop. Utilized Focal Loss instead of standard Cross-Entropy because Spot interruptions are rare (highly imbalanced dataset).
3. **`hyperparameter_tune.py`**: Ran a grid search script to find the optimal architecture and learning rates. Found ideal parameters: `d_model=128`, `num_heads=2`, `num_layers=2`, `lr=0.0005`.
4. **MLflow Integration**: Hooked the training loop into MLflow for live tracking of loss metrics, validation scores, and parameter logging.

---

## Commands

```bash
# Run the standard training loop
python ml/model/train.py

# Execute the hyperparameter grid search
python ml/model/hyperparameter_tune.py

# Launch the MLflow UI to view the tracked experiments
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

---

## Why (Key Decisions)

**Why a Transformer instead of an LSTM?**  
Transformers utilize Multi-Head Attention, allowing them to instantly correlate distant historical price signals without suffering from the vanishing gradient problems common in LSTMs. They also train significantly faster on modern hardware.

**Why use Focal Loss?**  
Spot instances are available ~95% of the time, meaning the data is massively imbalanced. The model would naturally default to always predicting "Safe". Focal Loss heavily penalizes the model for misclassifying the rare "Interruption" events, forcing it to learn the risk patterns.

**Why SQLite backend for MLflow (`sqlite:///mlruns.db`)?**  
During development on Windows, MLflow's default `file://` URI scheme caused path resolution errors. Migrating to a local SQLite backend resolved all URI crashing and stored the metrics cleanly in a single, git-ignored database file.

---

## Outputs

| Output | Description |
|--------|-------------|
| `spot_transformer.pt` | The compiled PyTorch model binary (5MB+). Ignored strictly in `.gitignore`. |
| `mlruns.db` | Tracking database containing all metrics, runs, and parameters (ignored in Git). |
| Optimal ML Parameters | `d_model=128`, `num_heads=2`, `num_layers=2`, `lr=0.0005`. |