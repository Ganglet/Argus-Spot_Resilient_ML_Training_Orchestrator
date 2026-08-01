import os
import json
import joblib
import torch
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, precision_recall_curve,
    f1_score, confusion_matrix,
)

from dataset import SpotPriceDataset, val_calibration_test_split
from transformer import SpotInterruptionPredictor

def _predict_raw(model, sequences, device, batch_size=256):
    """Raw sigmoid probabilities (uncalibrated) for a numpy array of windows."""
    probs = []
    with torch.no_grad():
        for i in range(0, len(sequences), batch_size):
            x = torch.tensor(sequences[i:i + batch_size], dtype=torch.float32).to(device)
            probs.append(torch.sigmoid(model(x)).cpu().numpy().flatten())
    return np.concatenate(probs)

def evaluate_checkpoint(model_dir: str, verbose: bool = True) -> dict:
    """
    1. Fits Platt scaling (a 1-feature logistic regression on the raw logit) on the
       SAME data train.py already used for early stopping - no new data spent.
       Platt scaling over isotonic regression because with ~100 positive examples,
       isotonic's many degrees of freedom are prone to overfitting the calibration
       curve itself; Platt's 2 parameters are far more stable at this sample size.
    2. Reports final PR-AUC / Brier / F1 / confusion matrix on a held-out test slice
       that was NEVER used for gradient updates, early stopping, or calibration -
       these are the numbers that go in the paper.

    model_dir: directory containing spot_transformer.pt / spot_scaler.joblib /
        model_metadata.json for the checkpoint to evaluate. Factored out from the
        CLI script so multi_seed_eval.py can evaluate several checkpoints in a row.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    model_path = os.path.join(model_dir, "spot_transformer.pt")
    scaler_path = os.path.join(model_dir, "spot_scaler.joblib")
    metadata_path = os.path.join(model_dir, "model_metadata.json")
    calibrator_path = os.path.join(model_dir, "spot_calibrator.joblib")

    def log(*args):
        if verbose:
            print(*args)

    with open(metadata_path) as f:
        metadata = json.load(f)
    scaler = joblib.load(scaler_path)

    device = torch.device('cpu')
    model = SpotInterruptionPredictor(
        num_features=metadata["num_features"],
        d_model=metadata["d_model"],
        nhead=metadata["nhead"],
        num_layers=metadata["num_layers"],
    )
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()

    dataset = SpotPriceDataset(csv_file_path=features_csv, scaler=scaler)
    calib_idx, test_idx = val_calibration_test_split(dataset.group_ranges, train_split=0.8)
    log(f"Calibration-fit set: {len(calib_idx)} windows | Held-out test set: {len(test_idx)} windows")

    calib_probs_raw = _predict_raw(model, dataset.sequences[calib_idx], device)
    calib_labels = dataset.labels[calib_idx]
    test_probs_raw = _predict_raw(model, dataset.sequences[test_idx], device)
    test_labels = dataset.labels[test_idx]

    log(f"Calibration set positives: {int(calib_labels.sum())} | Test set positives: {int(test_labels.sum())}")

    # Platt scaling: fit calibrated_prob = sigmoid(a * raw_logit + b) via logistic
    # regression on the RAW LOGIT (not the already-squashed probability - fitting on
    # the logit is the textbook Platt scaling formulation and keeps the mapping well
    # behaved at the extremes).
    eps = 1e-7
    calib_logits = np.log(np.clip(calib_probs_raw, eps, 1 - eps) / np.clip(1 - calib_probs_raw, eps, 1 - eps))
    platt = LogisticRegression()
    platt.fit(calib_logits.reshape(-1, 1), calib_labels)
    joblib.dump(platt, calibrator_path)

    test_logits = np.log(np.clip(test_probs_raw, eps, 1 - eps) / np.clip(1 - test_probs_raw, eps, 1 - eps))
    test_probs_calibrated = platt.predict_proba(test_logits.reshape(-1, 1))[:, 1]

    def report(name, labels, probs):
        pr_auc = average_precision_score(labels, probs)
        brier = brier_score_loss(labels, probs)
        precisions, recalls, thresholds = precision_recall_curve(labels, probs)
        f1s = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
        best_idx = np.argmax(f1s) if len(f1s) else 0
        base_rate = labels.sum() / len(labels)
        log(f"\n--- {name} (base rate {base_rate:.5f}) ---")
        log(f"PR-AUC: {pr_auc:.4f}  (lift over random: {pr_auc / base_rate:.2f}x)")
        log(f"Brier:  {brier:.4f}  (trivial always-safe baseline: {base_rate:.4f})")
        result = {"pr_auc": pr_auc, "brier": brier}
        if len(f1s):
            log(f"Best F1: {f1s[best_idx]:.4f} @ threshold {thresholds[best_idx]:.4f} "
                f"(precision {precisions[best_idx]:.4f}, recall {recalls[best_idx]:.4f})")
            cm = confusion_matrix(labels, (probs >= thresholds[best_idx]).astype(int))
            log(f"TN {cm[0][0]} FP {cm[0][1]} FN {cm[1][0]} TP {cm[1][1]}")
            result.update({
                "f1": f1s[best_idx], "precision": precisions[best_idx], "recall": recalls[best_idx],
                "tn": int(cm[0][0]), "fp": int(cm[0][1]), "fn": int(cm[1][0]), "tp": int(cm[1][1]),
            })
        return result

    log("\n" + "=" * 55)
    log("FINAL numbers on held-out test set (never used for training,")
    log("early stopping, or calibration):")
    log("=" * 55)
    uncalibrated = report("Uncalibrated (raw sigmoid)", test_labels, test_probs_raw)
    calibrated = report("Calibrated (Platt scaling)", test_labels, test_probs_calibrated)

    metadata["calibration"] = {
        "method": "platt_scaling",
        "calibrator_path": os.path.basename(calibrator_path),
        "test_set_size": len(test_idx),
        "test_pr_auc_uncalibrated": uncalibrated["pr_auc"],
        "test_pr_auc_calibrated": calibrated["pr_auc"],
        "test_brier_uncalibrated": uncalibrated["brier"],
        "test_brier_calibrated": calibrated["brier"],
    }
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    log(f"\nCalibrator saved to {calibrator_path}, metadata updated.")

    return {"uncalibrated": uncalibrated, "calibrated": calibrated, "test_positives": int(test_labels.sum())}

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    evaluate_checkpoint(base_dir)
