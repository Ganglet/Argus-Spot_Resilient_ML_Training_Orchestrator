import os
import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, f1_score, confusion_matrix, brier_score_loss
import xgboost as xgb

from dataset import SpotPriceDataset, temporal_split_indices, val_calibration_test_split
from feature_config import FEATURE_COLUMNS

def _report(name, labels, probs):
    pr_auc = average_precision_score(labels, probs)
    brier = brier_score_loss(labels, probs)
    precisions, recalls, thresholds = precision_recall_curve(labels, probs)
    f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
    best_idx = np.argmax(f1_scores) if len(f1_scores) else 0
    base_rate = labels.sum() / len(labels)
    print(f"\n--- {name} (n={len(labels)}, positives={int(labels.sum())}, base rate {base_rate:.5f}) ---")
    print(f"PR-AUC: {pr_auc:.4f}  (lift over random: {pr_auc / base_rate:.2f}x)")
    print(f"Brier:  {brier:.4f}  (trivial always-safe baseline: {base_rate:.4f})")
    if len(f1_scores):
        print(f"Best F1: {f1_scores[best_idx]:.4f} @ threshold {thresholds[best_idx]:.4f} "
              f"(precision {precisions[best_idx]:.4f}, recall {recalls[best_idx]:.4f})")
        cm = confusion_matrix(labels, (probs >= thresholds[best_idx]).astype(int))
        print(f"TN {cm[0][0]} FP {cm[0][1]} FN {cm[1][0]} TP {cm[1][1]}")
    return pr_auc, brier

def train_xgboost_baseline():
    """
    Baseline comparison for the Transformer: a 128-d attention model has vastly more
    parameters than the ~240 positive training examples it has to learn from at this
    label's rarity. Gradient-boosted trees are much lower-capacity and often win at this
    scale. Uses the LAST timestep of each window as the feature vector - the rolling
    15m/1h/6h stats already baked into each row summarize the recent history, so a full
    24-step flatten isn't needed the way it is for the Transformer.

    Trains on the same 80% train split, early-stops on the same calibration-fit half of
    val that the Transformer's early stopping uses, and reports FINAL numbers on the
    exact same held-out test slice calibrate_and_finalize.py uses for the Transformer -
    so the two models are compared on identical data, not just "similar" splits.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")

    dataset = SpotPriceDataset(csv_file_path=features_csv)
    train_idx, _ = temporal_split_indices(dataset.group_ranges, train_split=0.8)
    calib_idx, test_idx = val_calibration_test_split(dataset.group_ranges, train_split=0.8)

    # sequences: [N, seq_len, num_features] -> last timestep only -> [N, num_features]
    X = dataset.sequences[:, -1, :]
    y = dataset.labels

    X_train, y_train = X[train_idx], y[train_idx]
    X_calib, y_calib = X[calib_idx], y[calib_idx]
    X_test, y_test = X[test_idx], y[test_idx]

    pos = y_train.sum()
    neg = len(y_train) - pos
    scale_pos_weight = neg / max(pos, 1)
    print(f"Train: {len(y_train)} rows, {int(pos)} positive. scale_pos_weight={scale_pos_weight:.1f}")

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="aucpr",
        early_stopping_rounds=20,
        n_jobs=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_calib, y_calib)], verbose=False)

    test_probs = model.predict_proba(X_test)[:, 1]
    pr_auc, brier = _report("XGBoost — held-out test set", y_test, test_probs)

    model.save_model(os.path.join(base_dir, "spot_xgboost.json"))
    return pr_auc, brier

if __name__ == "__main__":
    train_xgboost_baseline()
