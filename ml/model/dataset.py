import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
import os

from feature_config import FEATURE_COLUMNS, SEQ_LENGTH, PREDICTION_HORIZON

class SpotPriceDataset(Dataset):
    """
    Creates sequences of historical timesteps from the engineered features
    to train our PyTorch Transformer.
    """
    def __init__(self, csv_file_path: str, seq_length: int = SEQ_LENGTH,
                 prediction_horizon: int = PREDICTION_HORIZON, scaler: StandardScaler = None):
        """
        seq_length: e.g., 24 timesteps * 5 mins = 2 hours of history
        prediction_horizon: predict if an interruption occurs in the next 3 timesteps (15 mins)
        scaler: a pre-fit StandardScaler to reuse (e.g. for the val split). If None, a new
            one is fit on this data and kept on self.scaler so callers can persist it.
        """
        self.seq_length = seq_length
        self.prediction_horizon = prediction_horizon

        # Load the feature-engineered dataset
        print(f"Loading features from {csv_file_path}...")
        df = pd.read_csv(csv_file_path, parse_dates=["timestamp"])
        df = df.sort_values(["instance_type", "availability_zone", "timestamp"])

        feature_cols = FEATURE_COLUMNS

        # Ground truth labels don't explicitly exist in the raw Spot API feed.
        # Spikes in price (e.g. > 1% suddenly) serve as our proxy label for Spot interruptions.
        df['prev_price'] = df.groupby(["instance_type", "availability_zone"])['spot_price'].shift(1)
        df['is_spike'] = (df['spot_price'] > df['prev_price'] * 1.01).astype(int)

        # Fit ONE global scaler across every instance/AZ, not a throwaway one per group.
        # A per-group scaler can never be reused at serving time (which instance's scaler
        # would you even load?). This scaler gets persisted to disk by train.py and loaded
        # by app.py so serving sees the exact same distribution the model was trained on.
        if scaler is None:
            self.scaler = StandardScaler()
            self.scaler.fit(df[feature_cols].fillna(0).values)
        else:
            self.scaler = scaler

        self.sequences = []
        self.labels = []
        # (start, end) index range in self.sequences for each instance/AZ group, in time
        # order. create_dataloaders uses these to split train/val WITHIN each group by
        # time, instead of randomly across all groups.
        self.group_ranges = []

        # We must group by instance/az so sequences don't overlap between wildly different servers
        print("Extracting sliding windows...")
        for _, group in df.groupby(["instance_type", "availability_zone"]):
            group = group.reset_index(drop=True)

            features_array = self.scaler.transform(group[feature_cols].fillna(0).values)
            labels_array = group["is_spike"].values

            num_rows = len(group)
            group_start = len(self.sequences)

            # Slide a window across the time series
            for i in range(num_rows - self.seq_length - self.prediction_horizon):
                # The historical window (X)
                window_x = features_array[i : i + self.seq_length]

                # Did an interruption/spike occur in the specific future horizon? (Y)
                # If ANY of the future timesteps are 1 (interrupted), label is 1
                future_y = labels_array[i + self.seq_length : i + self.seq_length + self.prediction_horizon]
                interruption_occurred = 1 if future_y.sum() > 0 else 0

                self.sequences.append(window_x)
                self.labels.append(interruption_occurred)

            self.group_ranges.append((group_start, len(self.sequences)))

        self.sequences = np.array(self.sequences, dtype=np.float32)
        self.labels = np.array(self.labels, dtype=np.float32)

        print(f"Dataset compiled. Total sequences: {len(self.sequences)}")
        print(f"Total interruptions (1s): {self.labels.sum()} | Normal (0s): {len(self.labels) - self.labels.sum()}")

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        # Convert the sliding window into a PyTorch Tensor
        x = torch.tensor(self.sequences[idx])
        y = torch.tensor(self.labels[idx]).unsqueeze(0) # [1] shaped
        return x, y

def temporal_split_indices(group_ranges, train_split: float = 0.8, purge: int = SEQ_LENGTH + PREDICTION_HORIZON):
    """
    Split EACH group by time (earlier windows -> train, later -> val), not randomly
    across the whole flat sequence list. Consecutive windows overlap by seq_length-1
    of their seq_length timesteps (stride-1 sliding window), so a random split puts
    near-duplicate windows on both sides of the train/val boundary - the model could
    partly memorize val examples via their train-side near-twins. A purge gap on
    either side of the cut removes every window whose timesteps overlap across the
    boundary, so val is honestly held-out future data. Shared by the Transformer
    dataloaders and any other model (e.g. the XGBoost baseline) trained on the same
    windows, so every model is compared on the exact same split.
    """
    train_indices = []
    val_indices = []
    for start, end in group_ranges:
        n = end - start
        cut = start + int(n * train_split)
        train_indices.extend(range(start, min(cut, end)))
        val_indices.extend(range(min(cut + purge, end), end))
    return train_indices, val_indices

def val_calibration_test_split(group_ranges, train_split: float = 0.8, purge: int = SEQ_LENGTH + PREDICTION_HORIZON):
    """
    Recreates train.py's exact 80/20 split (same formula, same purge), then further
    splits the 20% val portion in half (chronologically, with its own purge gap) into
    a calibration-fit set and a final held-out test set. The calibration-fit half is
    what train.py already uses for early stopping/model selection - fitting a
    calibrator on it doesn't touch any new data. The test half is never used for
    model selection or calibration, only for final reported numbers, so those numbers
    aren't circular.
    """
    calib_indices = []
    test_indices = []
    for start, end in group_ranges:
        n = end - start
        train_cut = start + int(n * train_split)
        val_start = min(train_cut + purge, end)
        val_n = end - val_start
        calib_cut = val_start + val_n // 2
        calib_indices.extend(range(val_start, min(calib_cut, end)))
        test_indices.extend(range(min(calib_cut + purge, end), end))
    return calib_indices, test_indices

def create_dataloaders(csv_path: str, batch_size: int = 64, train_split: float = 0.8):
    """
    Creates PyTorch DataLoaders to continuously stream our CSV into the Transformer.
    """
    dataset = SpotPriceDataset(csv_file_path=csv_path, seq_length=SEQ_LENGTH)

    train_indices, val_indices = temporal_split_indices(dataset.group_ranges, train_split)

    train_dataset = torch.utils.data.Subset(dataset, train_indices)
    val_dataset = torch.utils.data.Subset(dataset, val_indices)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # dataset.scaler is fit on the full data and must be persisted by the caller (train.py)
    # so the exact same transform can be applied at serving time.
    return train_loader, val_loader, dataset.sequences.shape[2], dataset.scaler # return num_features, scaler

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    
    train_loader, val_loader, num_features, _ = create_dataloaders(features_csv)
    
    print("\nTesting PyTorch DataLoader iteration:")
    for batch_x, batch_y in train_loader:
        print(f"Input batch shape: {batch_x.shape}")   # Expected: [64, 24, 13]
        print(f"Output batch shape: {batch_y.shape}")  # Expected: [64, 1]
        break