import torch
import os
import itertools
import mlflow
from dataset import create_dataloaders
from transformer import SpotInterruptionPredictor
from train import FocalLoss
from sklearn.metrics import average_precision_score

def tune_focal_loss():
    """
    train.py's alpha=0.75/gamma=2.0 were picked once and never checked against the
    real ~0.08% positive rate. Grid search both, ranked by val PR-AUC (not val loss -
    loss barely moves on a base rate this small, PR-AUC is what we actually care about).
    Each config trains on a limited number of batches, same pattern as
    hyperparameter_tune.py, to rank configs cheaply before committing to a full run.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Tuning Focal Loss hyperparameters on {device}...")

    train_loader, val_loader, input_features, _ = create_dataloaders(
        csv_path=features_csv, batch_size=128, train_split=0.8
    )

    param_grid = {
        'alpha': [0.25, 0.5, 0.75, 0.9],
        'gamma': [0.5, 1.0, 2.0, 3.0],
    }
    keys = param_grid.keys()
    combinations = [dict(zip(keys, v)) for v in itertools.product(*param_grid.values())]
    print(f"Total configs: {len(combinations)}")

    db_path = os.path.join(base_dir, "mlruns.db").replace("\\", "/")
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("Spot-FocalLoss-Tuning")

    max_train_batches = 150
    max_val_batches = 100

    results = []
    for idx, config in enumerate(combinations):
        print(f"\n--- Config {idx+1}/{len(combinations)}: {config} ---")
        with mlflow.start_run():
            mlflow.log_params(config)

            torch.manual_seed(42)
            model = SpotInterruptionPredictor(num_features=input_features, d_model=128, nhead=2, num_layers=2)
            model.to(device)
            criterion = FocalLoss(alpha=config['alpha'], gamma=config['gamma'])
            optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4)

            model.train()
            for batch_idx, (x, y) in enumerate(train_loader):
                if batch_idx >= max_train_batches:
                    break
                x, y = x.to(device), y.to(device)
                optimizer.zero_grad()
                loss = criterion(model(x), y)
                loss.backward()
                optimizer.step()

            model.eval()
            val_probs, val_labels = [], []
            with torch.no_grad():
                for batch_idx, (x, y) in enumerate(val_loader):
                    if batch_idx >= max_val_batches:
                        break
                    x = x.to(device)
                    probs = torch.sigmoid(model(x)).cpu().numpy().flatten()
                    val_probs.extend(probs)
                    val_labels.extend(y.numpy().flatten())

            pr_auc = average_precision_score(val_labels, val_probs)
            mlflow.log_metric("val_pr_auc_sample", pr_auc)
            print(f"    val PR-AUC (sampled): {pr_auc:.4f}")
            results.append((config, pr_auc))

    results.sort(key=lambda r: r[1], reverse=True)
    print("\n" + "=" * 50)
    print("Focal Loss tuning results (best first):")
    print("=" * 50)
    for config, pr_auc in results:
        print(f"  alpha={config['alpha']:<5} gamma={config['gamma']:<5} val_pr_auc={pr_auc:.4f}")
    best_config, best_pr_auc = results[0]
    print(f"\nBest: {best_config} -> val_pr_auc={best_pr_auc:.4f}")
    return best_config

if __name__ == "__main__":
    tune_focal_loss()
