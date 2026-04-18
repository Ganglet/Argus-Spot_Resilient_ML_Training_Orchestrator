# Feature Engineering & PyTorch Dataset

**Phase:** Week 2 — Feature Pipeline  
**Owner:** Person B  
**Status:** Complete — DataLoader objects ready for model consumption.

---

## Objective

Build a robust, automated feature engineering pipeline that transforms raw Spot price CSV data into sequenced, normalized tensors formatted specifically for a PyTorch deep learning model.

---

## What Was Done

1. **`feature_pipeline.py`**: Implemented a data pre-processing script that cleans the raw CSVs, handles missing timestamps, and normalizes the continuous Spot prices into standardized floats using scaling.
2. **`dataset.py`**: Implemented a custom PyTorch `Dataset` class (`torch.utils.data.Dataset`). It creates rolling sliding windows (sequences) of price data so the Transformer model can look back in time to predict future risk.
3. **DataLoaders**: Configured `DataLoader` objects to batch the sequences in memory, shuffle the training set, and parallelize data loading for efficient GPU/CPU training.

---

## Commands

```bash
# Run the pipeline to process raw CSVs into feature vectors
python ml/data/feature_pipeline.py

# Test the PyTorch Dataset to verify tensor shapes and batching
python ml/model/dataset.py
```

---

## Why (Key Decisions)

**Why use sliding windows?**  
Spot price interruptions are time-series events. A single point in time is not enough to predict an interruption; the model needs the last $N$ minutes of data to measure the *rate of change* (slope) in the price. Sliding windows provide this historical context.

**Why PyTorch DataLoaders?**    
Training a model on raw Pandas DataFrames is extremely slow. PyTorch DataLoaders convert data into PyTorch Tensors, handle memory batching automatically, and seamlessly transfer data to the GPU (CUDA) if available.

---

## Outputs

| Output | Description |
|--------|-------------|
| `PyTorch Tensors` | Normalized sliding window arrays shaping `(batch_size, sequence_length, features)`. |
| `DataLoader Iterator` | Iterable Python object that serves batches directly to the training loop. |
