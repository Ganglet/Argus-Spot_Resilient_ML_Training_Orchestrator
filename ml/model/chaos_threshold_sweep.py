import os
import json
import numpy as np

from measure_lead_time import _load_test_predictions, lead_time_at_threshold

def chaos_threshold_sweep(thresholds=None):
    """
    Week 7 chaos experiment: "terminate at various risk score levels." Rather than
    a fixed operating point (best-F1), sweep several risk thresholds and report what
    each one would actually do in production terms: how many alarms fire, how many
    are real (recall) vs wasted (false alarms), and the resulting lead time.

    Includes the operator CRD's actual default (riskThreshold: 0.65,
    demo/spotresilientjob.yaml) specifically to check whether it's even reachable
    by this model's real calibrated output range.
    """
    dataset, test_idx, test_probs, test_labels, group_spike_arrays, horizon, _, metadata = _load_test_predictions()

    print(f"Test set: {len(test_idx)} windows, {int(test_labels.sum())} positives, "
          f"score range [{test_probs.min():.5f}, {test_probs.max():.5f}]")

    if thresholds is None:
        # Span the model's actual observed score range, plus the operator's real
        # configured default (0.65) to show whether that default is even reachable.
        lo, hi = test_probs.min(), test_probs.max()
        thresholds = sorted(set(
            list(np.linspace(lo, hi, 6)) + [0.65]
        ))

    print(f"\n{'threshold':>10} {'alarms':>8} {'recall':>8} {'precision':>10} {'false_alarms':>13} {'mean_lead_s':>12}")
    rows = []
    for t in thresholds:
        r = lead_time_at_threshold(dataset, test_idx, test_probs, test_labels, group_spike_arrays, horizon, t)
        lead = f"{r.get('mean_lead_time_sec', float('nan')):.0f}" if "mean_lead_time_sec" in r else "n/a"
        print(f"{t:>10.5f} {r['n_alarms']:>8} {r['recall']:>8.3f} {r['precision']:>10.3f} "
              f"{r['false_alarms']:>13} {lead:>12}")
        rows.append(r)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(base_dir, "chaos_threshold_sweep.json")
    with open(out_path, "w") as f:
        json.dump({"score_range": [float(test_probs.min()), float(test_probs.max())], "rows": rows}, f, indent=2)
    print(f"\nSaved to {out_path}")

    default_threshold_row = next((r for r in rows if abs(r["threshold"] - 0.65) < 1e-9), None)
    if default_threshold_row and default_threshold_row["n_alarms"] == 0:
        print("\n*** The operator CRD's default riskThreshold (0.65) never fires against "
              "this model's real calibrated output (max observed score "
              f"{test_probs.max():.5f}). ***")

    return rows

if __name__ == "__main__":
    chaos_threshold_sweep()
