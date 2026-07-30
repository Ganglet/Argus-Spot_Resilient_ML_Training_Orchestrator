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

        # We must group by instance/az so sequences don't overlap between wildly different servers
        print("Extracting sliding windows...")
        for _, group in df.groupby(["instance_type", "availability_zone"]):
            group = group.reset_index(drop=True)

            features_array = self.scaler.transform(group[feature_cols].fillna(0).values)
            labels_array = group["is_spike"].values
            
            num_rows = len(group)
            
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

def create_dataloaders(csv_path: str, batch_size: int = 64, train_split: float = 0.8):
    """
    Creates PyTorch DataLoaders to continuously stream our CSV into the Transformer.
    """
    dataset = SpotPriceDataset(csv_file_path=csv_path, seq_length=SEQ_LENGTH)

    # Train / Val Split (no random shuffling prior to split for time-series)
    train_size = int(len(dataset) * train_split)
    val_size = len(dataset) - train_size

    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])

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