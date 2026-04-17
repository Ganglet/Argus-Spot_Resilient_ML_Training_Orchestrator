import torch
import torch.nn as nn
import torch.optim as optim
import os
import itertools
import mlflow
import mlflow.pytorch
from dataset import create_dataloaders
from transformer import SpotInterruptionPredictor
from train import FocalLoss

def tune_hyperparameters():
    """
    Executes a Grid Search to find the optimal Transformer hyperparameters
    for AWS Spot Interruption prediction. Logs all runs to MLflow.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    
    if not os.path.exists(features_csv):
        print(f"Error: {features_csv} not found.")
        return

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Executing Hyperparameter Grid Search on {device}...")

    # Load data once
    train_loader, val_loader, input_features = create_dataloaders(
        csv_path=features_csv,
        batch_size=64,
        train_split=0.8
    )

    # Define hyperparameter grid
    param_grid = {
        'd_model': [64, 128],
        'num_heads': [2, 4],
        'num_layers': [2, 4],
        'learning_rate': [1e-3, 5e-4]
    }
    
    # Generate all combinations
    keys = param_grid.keys()
    combinations = [dict(zip(keys, v)) for v in itertools.product(*param_grid.values())]
    
    print(f"Total configurations to test: {len(combinations)}")
    
    # Use SQLite backend for MLflow tracking (solves Windows path issues)
    db_path = os.path.join(base_dir, "mlruns.db").replace("\\", "/")
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("Spot-Hyperparameter-Tuning")
    
    epochs = 1  # Keeping it to 1 epoch per config for speed during the demo
    best_loss = float('inf')
    best_config = None
    
    for idx, config in enumerate(combinations):
        print(f"\n--- Run {idx+1}/{len(combinations)} ---")
        print(f"Testing config: {config}")
        
        with mlflow.start_run():
            mlflow.log_params(config)
            
            # Initialize model with current config
            model = SpotInterruptionPredictor(
                num_features=input_features, 
                d_model=config['d_model'], 
                nhead=config['num_heads'], 
                num_layers=config['num_layers']
            )
            model.to(device)

            criterion = FocalLoss(alpha=0.75, gamma=2.0)
            optimizer = optim.AdamW(model.parameters(), lr=config['learning_rate'])
            
            # Fast train loop over limited batches (e.g., 50 batches per config) to find the best fast-learner
            model.train()
            running_loss = 0.0
            max_batches_per_run = 50 
            
            for batch_idx, (x, y) in enumerate(train_loader):
                if batch_idx >= max_batches_per_run:
                    break
                    
                x, y = x.to(device), y.to(device)
                optimizer.zero_grad()
                raw_logits = model(x)
                loss = criterion(raw_logits, y)
                loss.backward()
                optimizer.step()
                running_loss += loss.item()
            
            avg_train_loss = running_loss / max_batches_per_run
            mlflow.log_metric("train_loss_sample", avg_train_loss)
            
            # Fast validation evaluation
            model.eval()
            val_loss = 0.0
            val_batches = min(20, len(val_loader))
            
            with torch.no_grad():
                for batch_idx, (x, y) in enumerate(val_loader):
                    if batch_idx >= val_batches: break
                    x, y = x.to(device), y.to(device)
                    val_logits = model(x)
                    loss = criterion(val_logits, y)
                    val_loss += loss.item()
            
            avg_val_loss = val_loss / val_batches if val_batches > 0 else float('inf')
            mlflow.log_metric("val_loss_sample", avg_val_loss)
            
            print(f"Result -> Train Loss: {avg_train_loss:.4f} | Val Loss: {avg_val_loss:.4f}")
            
            if avg_val_loss < best_loss:
                best_loss = avg_val_loss
                best_config = config
    
    print("\n=========================================")
    print(f"🏆 Best Hyperparameters Found!")
    print(f"Lowest Validation Loss: {best_loss:.4f}")
    print(f"Best Config: {best_config}")
    print("=========================================")

if __name__ == "__main__":
    tune_hyperparameters()