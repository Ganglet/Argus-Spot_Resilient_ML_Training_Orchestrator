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

def measure_lead_time():
    """
    Empirical lead time against the PROXY label (price spike >1%), not real AWS
    interruptions - that data isn't available (see docs/objective3_result.md). This
    answers a narrower, honest question: for windows the model correctly flags as
    risky (true positives at the best-F1 threshold), how many minutes before the
    actual proxy spike did the flag fire?

    Bounded by construction to [5, 15] minutes: the model's own label only looks
    PREDICTION_HORIZON (3) steps of 5 min each into the future, so it can never
    claim more lead time than that against this label - a true positive by
    definition means the spike is 1, 2, or 3 steps ahead when the window ends.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    model_path = os.path.join(base_dir, "spot_transformer.pt")
    scaler_path = os.path.join(base_dir, "spot_scaler.joblib")
    metadata_path = os.path.join(base_dir, "model_metadata.json")
    calibrator_path = os.path.join(base_dir, "spot_calibrator.joblib")

    with open(metadata_path) as f:
        metadata = json.load(f)
    scaler = joblib.load(scaler_path)
    calibrator = joblib.load(calibrator_path) if os.path.exists(calibrator_path) else None

    device = torch.device('cpu')
    model = SpotInterruptionPredictor(
        num_features=metadata["num_features"], d_model=metadata["d_model"],
        nhead=metadata["nhead"], num_layers=metadata["num_layers"],
    )
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()

    dataset = SpotPriceDataset(csv_file_path=features_csv, scaler=scaler)
    _, test_idx = val_calibration_test_split(dataset.group_ranges, train_split=0.8)

    # Recompute per-row is_spike, grouped in the SAME order dataset.py uses, so a
    # window index can be mapped back to exactly WHICH future row the proxy spike
    # happens on - dataset.labels only says "somewhere in the next horizon rows".
    df = pd.read_csv(features_csv, parse_dates=["timestamp"])
    df = df.sort_values(["instance_type", "availability_zone", "timestamp"])
    df['prev_price'] = df.groupby(["instance_type", "availability_zone"])['spot_price'].shift(1)
    df['is_spike'] = (df['spot_price'] > df['prev_price'] * 1.01).astype(int)

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

    precisions, recalls, thresholds = precision_recall_curve(test_labels, test_probs)
    f1s = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
    best_idx = np.argmax(f1s) if len(f1s) else 0
    threshold = thresholds[best_idx] if len(thresholds) else 0.5
    print(f"Using best-F1 threshold: {threshold:.4f} (F1={f1s[best_idx]:.4f})")

    lead_times_steps = []
    for flat_idx, prob, label in zip(test_idx, test_probs, test_labels):
        if label != 1 or prob < threshold:
            continue  # only true positives
        for g, (start, end) in enumerate(dataset.group_ranges):
            if start <= flat_idx < end:
                local_i = flat_idx - start
                spikes = group_spike_arrays[g]
                horizon = spikes[local_i + SEQ_LENGTH: local_i + SEQ_LENGTH + PREDICTION_HORIZON]
                if horizon.sum() > 0:
                    offset = int(np.argmax(horizon))  # earliest spike row within the horizon
                    lead_times_steps.append(offset + 1)  # 1-indexed step count
                break

    lead_times_steps = np.array(lead_times_steps)
    lead_times_seconds = lead_times_steps * 5 * 60  # 5-min timesteps

    print(f"\nTrue positives at this threshold: {len(lead_times_steps)}")
    result = {"threshold": float(threshold), "n_true_positives": int(len(lead_times_steps))}
    if len(lead_times_steps):
        print(f"Lead time steps (1-3, each = 5 min): {lead_times_steps.tolist()}")
        print(f"Mean lead time: {lead_times_seconds.mean():.1f}s ({lead_times_seconds.mean()/60:.2f} min)")
        print(f"Median lead time: {np.median(lead_times_seconds):.1f}s")
        print(f"Min/Max: {lead_times_seconds.min():.0f}s / {lead_times_seconds.max():.0f}s")
        result.update({
            "mean_lead_time_sec": float(lead_times_seconds.mean()),
            "median_lead_time_sec": float(np.median(lead_times_seconds)),
            "min_lead_time_sec": float(lead_times_seconds.min()),
            "max_lead_time_sec": float(lead_times_seconds.max()),
        })
    else:
        print("No true positives at this threshold - can't measure lead time.")

    metadata["proxy_lead_time"] = result
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"\nSaved to {metadata_path}")

    return result

if __name__ == "__main__":
    measure_lead_time()
