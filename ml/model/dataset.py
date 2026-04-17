import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
import os

class SpotPriceDataset(Dataset):
    """
    Creates sequences of historical timesteps from the engineered features
    to train our PyTorch Transformer.
    """
    def __init__(self, csv_file_path: str, seq_length: int = 24, prediction_horizon: int = 3):
        """
        seq_length: e.g., 24 timesteps * 5 mins = 2 hours of history
        prediction_horizon: predict if an interruption occurs in the next 3 timesteps (15 mins)
        """
        self.seq_length = seq_length
        self.prediction_horizon = prediction_horizon
        
        # Load the feature-engineered dataset
        print(f"Loading features from {csv_file_path}...")
        df = pd.read_csv(csv_file_path, parse_dates=["timestamp"])
        df = df.sort_values(["instance_type", "availability_zone", "timestamp"])
        
        # Identify columns to feed the model
        feature_cols = [
            "spot_price", "price_delta", 
            "rolling_mean_15m", "rolling_std_15m",
            "rolling_mean_1h", "rolling_std_1h",
            "rolling_mean_6h", "rolling_std_6h",
            "normalized_ratio", 
            "sin_time_day", "cos_time_day",
            "sin_day_week", "cos_day_week"
        ]
        
        # Ground truth labels don't explicitly exist in the raw Spot API feed.
        # Spikes in price (e.g. > 1% suddenly) serve as our proxy label for Spot interruptions.
        df['prev_price'] = df.groupby(["instance_type", "availability_zone"])['spot_price'].shift(1)
        df['is_spike'] = (df['spot_price'] > df['prev_price'] * 1.01).astype(int)
        
        self.sequences = []
        self.labels = []
        
        # We must group by instance/az so sequences don't overlap between wildly different servers
        print("Extracting sliding windows...")
        for _, group in df.groupby(["instance_type", "availability_zone"]):
            group = group.reset_index(drop=True)
            
            # Normalize features manually for the model's stability
            scaler = StandardScaler()
            features_array = scaler.fit_transform(group[feature_cols].fillna(0).values)
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
    dataset = SpotPriceDataset(csv_file_path=csv_path, seq_length=24)
    
    # Train / Val Split (no random shuffling prior to split for time-series)
    train_size = int(len(dataset) * train_split)
    val_size = len(dataset) - train_size
    
    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    
    return train_loader, val_loader, dataset.sequences.shape[2] # return num_features

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    
    train_loader, val_loader, num_features = create_dataloaders(features_csv)
    
    print("\nTesting PyTorch DataLoader iteration:")
    for batch_x, batch_y in train_loader:
        print(f"Input batch shape: {batch_x.shape}")   # Expected: [64, 24, 13]
        print(f"Output batch shape: {batch_y.shape}")  # Expected: [64, 1]
        break