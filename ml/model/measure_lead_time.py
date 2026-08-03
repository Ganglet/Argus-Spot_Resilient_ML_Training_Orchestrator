import os
import json
import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import precision_recall_curve

from dataset import SpotPriceDataset, val_calibration_test_split
from transformer import SpotInterruptionPredictor
from feature_config import FEATURE_COLUMNS, SEQ_LENGTH, PREDICTION_HORIZON

def _load_test_predictions(model_dir=None):
    """
    Shared setup for lead-time analysis: loads the shipped model + calibrator,
    scores the held-out test set, and builds per-group is_spike arrays so a
    window index can be mapped back to exactly WHICH future row the proxy
    spike happens on (dataset.labels only says "somewhere in the horizon").
    Factored out so a threshold sweep doesn't reload the model/data per threshold.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = model_dir or base_dir
    features_csv = os.path.join(base_dir, "../data/features.csv")
    metadata_path = os.path.join(model_dir, "model_metadata.json")

    with open(metadata_path) as f:
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

    df = pd.read_csv(features_csv, parse_dates=["timestamp"])
    df = df.sort_values(["instance_type", "availability_zone", "timestamp"])
    df['prev_price'] = df.groupby(["instance_type", "availability_zone"])['spot_price'].shift(1)
    df['is_spike'] = (df['spot_price'] > df['prev_price'] * metadata.get("spike_threshold", 1.01)).astype(int)
    group_spike_arrays = [g["is_spike"].values for _, g in df.groupby(["instance_type", "availability_zone"])]
    assert len(group_spike_arrays) == len(dataset.group_ranges)

    def predict_raw(seqs, bs=256):
        probs = []
        with torch.no_grad():
            for i in range(0, len(seqs), bs):
                x = torch.tensor(seqs[i:i + bs], dtype=torch.float32)
                probs.append(torch.sigmoid(model(x)).numpy().flatten())
        return np.concatenate(probs)

    test_probs_raw = predict_raw(dataset.sequences[test_idx])
    test_labels = dataset.labels[test_idx]

    if calibrator is not None:
        eps = 1e-7
        logits = np.log(np.clip(test_probs_raw, eps, 1 - eps) / np.clip(1 - test_probs_raw, eps, 1 - eps))
        test_probs = calibrator.predict_proba(logits.reshape(-1, 1))[:, 1]
    else:
        test_probs = test_probs_raw

    horizon = metadata.get("prediction_horizon", PREDICTION_HORIZON)
    return dataset, test_idx, test_probs, test_labels, group_spike_arrays, horizon, metadata_path, metadata

def lead_time_at_threshold(dataset, test_idx, test_probs, test_labels, group_spike_arrays, horizon, threshold):
    """Lead time + alarm-rate stats for ONE threshold, reusing already-scored predictions."""
    lead_times_steps = []
    n_alarms = int((test_probs >= threshold).sum())
    for flat_idx, prob, label in zip(test_idx, test_probs, test_labels):
        if label != 1 or prob < threshold:
            continue
        for g, (start, end) in enumerate(dataset.group_ranges):
            if start <= flat_idx < end:
                local_i = flat_idx - start
                spikes = group_spike_arrays[g]
                fut = spikes[local_i + SEQ_LENGTH: local_i + SEQ_LENGTH + horizon]
                if fut.sum() > 0:
                    offset = int(np.argmax(fut))
                    lead_times_steps.append(offset + 1)
                break

    n_true_positives = int(test_labels[test_probs >= threshold].sum())
    n_positives = int(test_labels.sum())
    lead_times_seconds = np.array(lead_times_steps) * 5 * 60
    result = {
        "threshold": float(threshold),
        "n_alarms": n_alarms,
        "n_true_positives": n_true_positives,
        "n_positives": n_positives,
        "recall": n_true_positives / n_positives if n_positives else 0.0,
        "false_alarms": n_alarms - n_true_positives,
        "precision": n_true_positives / n_alarms if n_alarms else 0.0,
    }
    if len(lead_times_seconds):
        result["mean_lead_time_sec"] = float(lead_times_seconds.mean())
        result["median_lead_time_sec"] = float(np.median(lead_times_seconds))
    return result

def measure_lead_time():
    """
    Empirical lead time against the PROXY label (price spike >1%), not real AWS
    interruptions - that data isn't available (see docs/objective3_result.md). This
    answers a narrower, honest question: for windows the model correctly flags as
    risky (true positives at the best-F1 threshold), how many minutes before the
    actual proxy spike did the flag fire?

    Bounded by construction to [5, horizon*5] minutes: the model's own label only
    looks `prediction_horizon` steps of 5 min each into the future, so it can never
    claim more lead time than that against this label.
    """
    dataset, test_idx, test_probs, test_labels, group_spike_arrays, horizon, metadata_path, metadata = _load_test_predictions()

    precisions, recalls, thresholds = precision_recall_curve(test_labels, test_probs)
    f1s = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
    best_idx = np.argmax(f1s) if len(f1s) else 0
    threshold = thresholds[best_idx] if len(thresholds) else 0.5
    print(f"Using best-F1 threshold: {threshold:.4f} (F1={f1s[best_idx]:.4f})")

    result = lead_time_at_threshold(dataset, test_idx, test_probs, test_labels, group_spike_arrays, horizon, threshold)
    print(f"\nTrue positives at this threshold: {result['n_true_positives']}")
    if "mean_lead_time_sec" in result:
        print(f"Mean lead time: {result['mean_lead_time_sec']:.1f}s ({result['mean_lead_time_sec']/60:.2f} min)")
        print(f"Median lead time: {result['median_lead_time_sec']:.1f}s")
    else:
        print("No true positives at this threshold - can't measure lead time.")

    metadata["proxy_lead_time"] = result
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"\nSaved to {metadata_path}")
    return result

if __name__ == "__main__":
    measure_lead_time()
