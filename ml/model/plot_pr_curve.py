import os
import json
import joblib
import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import precision_recall_curve, average_precision_score

from dataset import SpotPriceDataset, val_calibration_test_split
from transformer import SpotInterruptionPredictor
from feature_config import PREDICTION_HORIZON

def plot_pr_curve(model_dir: str = None, out_path: str = None):
    """
    PR curve + threshold analysis on the held-out test set (same split
    calibrate_and_finalize.py uses for final numbers) - the week 7 evaluation
    report deliverable (PR curves, threshold analysis).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = model_dir or base_dir
    features_csv = os.path.join(base_dir, "../data/features.csv")
    out_path = out_path or os.path.join(base_dir, "../../docs/figures/pr_curve.png")

    with open(os.path.join(model_dir, "model_metadata.json")) as f:
        metadata = json.load(f)
    scaler = joblib.load(os.path.join(model_dir, "spot_scaler.joblib"))
    calibrator_path = os.path.join(model_dir, "spot_calibrator.joblib")
    calibrator = joblib.load(calibrator_path) if os.path.exists(calibrator_path) else None

    device = torch.device('cpu')
    model = SpotInterruptionPredictor(
        num_features=metadata["num_features"], d_model=metadata["d_model"],
        nhead=metadata["nhead"], num_layers=metadata["num_layers"],
    )
    model.load_state_dict(torch.load(os.path.join(model_dir, "spot_transformer.pt"), map_location=device))
    model.eval()

    dataset = SpotPriceDataset(
        csv_file_path=features_csv, scaler=scaler,
        prediction_horizon=metadata.get("prediction_horizon", PREDICTION_HORIZON),
        spike_threshold=metadata.get("spike_threshold", 1.01),
    )
    _, test_idx = val_calibration_test_split(dataset.group_ranges, train_split=0.8)
    labels = dataset.labels[test_idx]

    probs = []
    with torch.no_grad():
        for i in range(0, len(test_idx), 256):
            x = torch.tensor(dataset.sequences[test_idx[i:i + 256]], dtype=torch.float32)
            probs.append(torch.sigmoid(model(x)).numpy().flatten())
    probs = np.concatenate(probs)

    if calibrator is not None:
        eps = 1e-7
        logits = np.log(np.clip(probs, eps, 1 - eps) / np.clip(1 - probs, eps, 1 - eps))
        probs = calibrator.predict_proba(logits.reshape(-1, 1))[:, 1]

    precisions, recalls, thresholds = precision_recall_curve(labels, probs)
    pr_auc = average_precision_score(labels, probs)
    base_rate = labels.sum() / len(labels)

    f1s = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
    best_idx = np.argmax(f1s) if len(f1s) else 0
    best_threshold = thresholds[best_idx] if len(thresholds) else 0.5

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(recalls, precisions, label=f"model (PR-AUC={pr_auc:.4f}, {pr_auc/base_rate:.1f}x random)")
    ax.axhline(base_rate, linestyle="--", color="gray", label=f"random baseline ({base_rate:.4f})")
    ax.scatter([recalls[best_idx]], [precisions[best_idx]], color="red", zorder=5,
               label=f"best-F1 threshold ({best_threshold:.4f})")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall — held-out test set (proxy label)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_ylim(0, max(precisions) * 1.15)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved PR curve to {out_path}")

    # Threshold analysis table: how precision/recall/checkpoint-overhead trade off
    # at several concrete operating points, not just the single best-F1 one.
    print("\nThreshold analysis (subset of points along the curve):")
    print(f"{'threshold':>10} {'precision':>10} {'recall':>10} {'alarms/positive':>16}")
    n = len(thresholds)
    sample_idx = sorted(set([0, n // 4, n // 2, 3 * n // 4, best_idx, n - 1])) if n else []
    rows = []
    for i in sample_idx:
        if i >= len(precisions) - 1:
            continue
        p, r, t = precisions[i], recalls[i], thresholds[i]
        alarms_per_positive = (1 / p - 1) if p > 0 else float("inf")
        marker = " <- best F1" if i == best_idx else ""
        print(f"{t:>10.4f} {p:>10.4f} {r:>10.4f} {alarms_per_positive:>16.1f}{marker}")
        rows.append({"threshold": float(t), "precision": float(p), "recall": float(r),
                      "false_alarms_per_true_positive": float(alarms_per_positive)})

    return {"pr_auc": float(pr_auc), "base_rate": float(base_rate),
            "best_threshold": float(best_threshold), "threshold_table": rows}

if __name__ == "__main__":
    plot_pr_curve()
