import torch
import os
import itertools
import mlflow
from dataset import create_dataloaders
from transformer import SpotInterruptionPredictor
from train import FocalLoss
from sklearn.metrics import average_precision_score

def tune_data_config():
    """
    Three label/data-pipeline choices were never tuned, just picked once:
      - spike_threshold: is_spike = price > prev_price * 1.01 (>1% jump)
      - prediction_horizon: 3 steps (15 min) ahead
      - oversample: off (Focal Loss alone handles the ~0.08% positive rate)
    Quick grid search (limited train batches, same pattern as tune_focal_loss.py) to
    rank configs by val PR-AUC before committing to a full multi-seed run on the winner.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Tuning data config on {device}...")

    # thresholds below 1.003 or above 1.01 aren't worth testing: raw positive-row counts
    # at 1.02/1.03 are 5/0 (too sparse to learn from at all), and we already have 1.01
    # as the current baseline.
    param_grid = {
        'spike_threshold': [1.003, 1.005, 1.01],
        'prediction_horizon': [1, 3, 6],
        'oversample': [True, False],
    }
    keys = param_grid.keys()
    combinations = [dict(zip(keys, v)) for v in itertools.product(*param_grid.values())]
    print(f"Total configs: {len(combinations)}")

    db_path = os.path.join(base_dir, "mlruns.db").replace("\\", "/")
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("Spot-DataConfig-Tuning")

    max_train_batches = 150
    max_val_batches = 100

    results = []
    for idx, config in enumerate(combinations):
        print(f"\n--- Config {idx+1}/{len(combinations)}: {config} ---")
        with mlflow.start_run():
            mlflow.log_params(config)

            train_loader, val_loader, input_features, _ = create_dataloaders(
                csv_path=features_csv, batch_size=128, train_split=0.8,
                prediction_horizon=config['prediction_horizon'],
                spike_threshold=config['spike_threshold'],
                oversample=config['oversample'],
            )

            torch.manual_seed(42)
            model = SpotInterruptionPredictor(num_features=input_features, d_model=128, nhead=2, num_layers=2)
            model.to(device)
            criterion = FocalLoss(alpha=0.75, gamma=1.0)
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

            if sum(val_labels) == 0:
                print("    no positives in sampled val batches, skipping")
                continue
            pr_auc = average_precision_score(val_labels, val_probs)
            # Different (threshold, horizon) combos relabel the data - each has its own
            # base rate, and PR-AUC's own "no skill" baseline rises with the base rate.
            # Comparing raw PR-AUC across configs with different base rates isn't a fair
            # comparison (a config can "look better" purely because the task got easier,
            # not because the model discriminates better) - rank by lift over THIS
            # config's own base rate instead.
            base_rate = sum(val_labels) / len(val_labels)
            lift = pr_auc / base_rate
            mlflow.log_metric("val_pr_auc_sample", pr_auc)
            mlflow.log_metric("val_lift_sample", lift)
            print(f"    val PR-AUC (sampled): {pr_auc:.4f}  base_rate: {base_rate:.5f}  lift: {lift:.2f}x")
            results.append((config, pr_auc, base_rate, lift))

    results.sort(key=lambda r: r[3], reverse=True)
    print("\n" + "=" * 60)
    print("Data config tuning results (best lift first):")
    print("=" * 60)
    for config, pr_auc, base_rate, lift in results:
        print(f"  {config} -> pr_auc={pr_auc:.4f}  base_rate={base_rate:.5f}  lift={lift:.2f}x")
    best_config, best_pr_auc, best_base_rate, best_lift = results[0]
    print(f"\nBest by lift: {best_config} -> lift={best_lift:.2f}x (pr_auc={best_pr_auc:.4f}, base_rate={best_base_rate:.5f})")
    return best_config

if __name__ == "__main__":
    tune_data_config()
