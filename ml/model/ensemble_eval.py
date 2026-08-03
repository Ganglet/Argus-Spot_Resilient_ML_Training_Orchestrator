import os
import glob
import json
import joblib
import itertools
import numpy as np
import torch
from sklearn.metrics import (
    average_precision_score, brier_score_loss, precision_recall_curve, confusion_matrix,
)

from dataset import SpotPriceDataset, val_calibration_test_split
from transformer import SpotInterruptionPredictor
from feature_config import PREDICTION_HORIZON

def _predict_raw(model, sequences, device, batch_size=256):
    probs = []
    with torch.no_grad():
        for i in range(0, len(sequences), batch_size):
            x = torch.tensor(sequences[i:i + batch_size], dtype=torch.float32).to(device)
            probs.append(torch.sigmoid(model(x)).cpu().numpy().flatten())
    return np.concatenate(probs)

def ensemble_eval(checkpoints_dir: str):
    """
    Averages predictions from every seed_N/ checkpoint under checkpoints_dir on the
    same held-out test set individual seeds were scored on - a legitimate way to
    exploit the run-to-run variance found in docs/objective3_result.md (5 seeds of
    the identical config scored 0.0183-0.0500 PR-AUC) rather than just picking the
    lucky one.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")

    seed_dirs = sorted(glob.glob(os.path.join(checkpoints_dir, "seed_*")))
    if not seed_dirs:
        raise FileNotFoundError(f"No seed_* checkpoints under {checkpoints_dir}")
    print(f"Found {len(seed_dirs)} seed checkpoints: {[os.path.basename(d) for d in seed_dirs]}")

    with open(os.path.join(seed_dirs[0], "model_metadata.json")) as f:
        metadata0 = json.load(f)
    scaler = joblib.load(os.path.join(seed_dirs[0], "spot_scaler.joblib"))

    device = torch.device('cpu')
    dataset = SpotPriceDataset(
        csv_file_path=features_csv, scaler=scaler,
        prediction_horizon=metadata0.get("prediction_horizon", PREDICTION_HORIZON),
        spike_threshold=metadata0.get("spike_threshold", 1.01),
    )
    calib_idx, test_idx = val_calibration_test_split(dataset.group_ranges, train_split=0.8)
    calib_labels = dataset.labels[calib_idx]
    test_labels = dataset.labels[test_idx]

    all_calib_probs, all_test_probs = [], []
    for seed_dir in seed_dirs:
        with open(os.path.join(seed_dir, "model_metadata.json")) as f:
            metadata = json.load(f)
        model = SpotInterruptionPredictor(
            num_features=metadata["num_features"], d_model=metadata["d_model"],
            nhead=metadata["nhead"], num_layers=metadata["num_layers"],
        )
        model.load_state_dict(torch.load(os.path.join(seed_dir, "spot_transformer.pt"), map_location=device))
        model.eval()
        all_calib_probs.append(_predict_raw(model, dataset.sequences[calib_idx], device))
        all_test_probs.append(_predict_raw(model, dataset.sequences[test_idx], device))
        print(f"  {os.path.basename(seed_dir)}: calib PR-AUC = {average_precision_score(calib_labels, all_calib_probs[-1]):.4f}"
              f"  | test PR-AUC = {average_precision_score(test_labels, all_test_probs[-1]):.4f}")

    # Which seeds to include is itself a choice - picking whichever subset scores best
    # on the TEST set would be the same cherry-picking this whole project has been
    # trying to avoid (see docs/objective3_result.md's run-variance section). Instead,
    # brute-force every non-empty subset (2^N-1, trivial at N=5) and pick the one that
    # scores best on the CALIBRATION set - data already used for Platt scaling, not new
    # data, and never touched by test-set reporting. Only the winning subset's test
    # score gets reported.
    n = len(seed_dirs)
    best_subset, best_calib_pr_auc = None, -1.0
    for r in range(1, n + 1):
        for subset in itertools.combinations(range(n), r):
            probs = np.mean([all_calib_probs[i] for i in subset], axis=0)
            pr_auc = average_precision_score(calib_labels, probs)
            if pr_auc > best_calib_pr_auc:
                best_calib_pr_auc = pr_auc
                best_subset = subset
    chosen = [os.path.basename(seed_dirs[i]) for i in best_subset]
    print(f"\nBest subset by CALIBRATION-set PR-AUC ({best_calib_pr_auc:.4f}): {chosen}")

    ensemble_calib_probs = np.mean([all_calib_probs[i] for i in best_subset], axis=0)
    ensemble_test_probs = np.mean([all_test_probs[i] for i in best_subset], axis=0)

    # Calibrate the ensemble itself (its own averaged output has its own scale)
    from sklearn.linear_model import LogisticRegression
    eps = 1e-7
    calib_logits = np.log(np.clip(ensemble_calib_probs, eps, 1 - eps) / np.clip(1 - ensemble_calib_probs, eps, 1 - eps))
    platt = LogisticRegression()
    platt.fit(calib_logits.reshape(-1, 1), calib_labels)
    test_logits = np.log(np.clip(ensemble_test_probs, eps, 1 - eps) / np.clip(1 - ensemble_test_probs, eps, 1 - eps))
    ensemble_test_calibrated = platt.predict_proba(test_logits.reshape(-1, 1))[:, 1]

    def report(name, labels, probs):
        pr_auc = average_precision_score(labels, probs)
        brier = brier_score_loss(labels, probs)
        base_rate = labels.sum() / len(labels)
        precisions, recalls, thresholds = precision_recall_curve(labels, probs)
        f1s = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
        best_idx = np.argmax(f1s) if len(f1s) else 0
        print(f"\n--- {name} (base rate {base_rate:.5f}) ---")
        print(f"PR-AUC: {pr_auc:.4f}  (lift: {pr_auc / base_rate:.2f}x)")
        print(f"Brier:  {brier:.4f}  (trivial baseline: {base_rate:.4f})")
        if len(f1s):
            print(f"Best F1: {f1s[best_idx]:.4f} (precision {precisions[best_idx]:.4f}, recall {recalls[best_idx]:.4f})")
            cm = confusion_matrix(labels, (probs >= thresholds[best_idx]).astype(int))
            print(f"TN {cm[0][0]} FP {cm[0][1]} FN {cm[1][0]} TP {cm[1][1]}")
        return {"pr_auc": float(pr_auc), "brier": float(brier), "lift": float(pr_auc / base_rate)}

    print(f"\n{'='*55}\nENSEMBLE ({len(best_subset)} of {len(seed_dirs)} seeds, chosen via calibration set) - held-out test set\n{'='*55}")
    result = report("Ensemble (calibrated)", test_labels, ensemble_test_calibrated)
    result["chosen_seeds"] = chosen
    result["n_available_seeds"] = n
    return result

if __name__ == "__main__":
    import sys
    checkpoints_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_ensemble_checkpoints")
    ensemble_eval(checkpoints_dir)
