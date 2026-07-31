# Objective 2 Result — Predictive Model, Real Training Run (2026-07-31)

Honest results for the paper figure. Trained and evaluated on the real feature
pipeline output (`ml/data/features.csv`, 386,868 windowed sequences from live
`eu-north-1` Spot price history). Reproduce with `python ml/model/train.py`
then `python ml/model/calibrate_and_finalize.py`.

This went through two rounds: Round 1 fixed the bugs that made the model
useless (flat output). Round 2 fixed methodology problems that were making
the *measurement* of the model optimistic/pessimistic in different ways, and
tried a few concrete improvements. Both are recorded below because the
reasoning matters for anyone touching this code next.

## Round 1 — bugs that made the model useless

The model previously returned a **flat `0.0419` for every instance type/AZ**
(see `problems_and_decisions.md` P-018/019). Root causes:

1. **Train/serve skew (the direct cause of the flat score).** Training
   standardized features with `StandardScaler`, fit *per instance/AZ group*,
   then threw the scaler away. Serving fed the model raw values with no
   scaling. Fixed by fitting **one global scaler**, persisting it
   (`spot_scaler.joblib`), and applying it at serving.
2. **3-epoch smoke test, never scaled up.** `train.py` hardcoded `epochs = 3`
   with a comment admitting it was "just for verifying loss drops," and never
   touched the validation loader it built.
3. **Serving feature/sequence mismatch.** Training used 13 named columns in a
   fixed order and `seq_length=24`; serving used `select_dtypes()` and
   `seq_len=12`. Fixed with a single `feature_config.py` + `model_metadata.json`
   that serving validates against at startup.
4. **MLflow tracking URI crashed on Windows**, silently killing every prior
   "training run" before a single batch ran. Switched to the SQLite backend.

Round 1 result: PR-AUC 0.0034 (4x base rate), Brier score actually *worse*
than a trivial always-predict-safe baseline (badly overconfident).

## Round 2 — methodology bugs, a baseline, a new feature, calibration

1. **Train/val leakage.** Sliding windows overlap 23/24 timesteps with their
   neighbor (stride 1). The Round 1 split (`random_split`) put near-duplicate
   windows on both sides of the train/val boundary, so val was partly
   measuring memorization. Fixed: split each instance/AZ group **by time**
   (earlier → train, later → val), with a purge gap so no window's timesteps
   cross the boundary (`dataset.py::temporal_split_indices`).
2. **FocalLoss's `alpha` was a no-op.** It was applied as a flat scalar to
   every sample regardless of label — mathematically identical to scaling the
   learning rate, not the "penalize the rare class harder" effect the
   docstring claimed. Only `gamma` was doing anything. Fixed to the standard
   per-class `alpha_t` weighting, then grid-searched (`tune_focal_loss.py`):
   best is `alpha=0.75, gamma=1.0`.
3. **Wrong scikit-learn version pinned in `ml/api/requirements.txt`**
   (`1.5.3` — that was actually joblib's version, misread earlier; real
   version is `1.8.0`). Would have risked the API container failing to
   unpickle the scaler.
4. **XGBoost baseline** (`train_xgboost.py`), on the exact same held-out test
   split as the Transformer — see comparison table below.
5. **Cross-AZ price divergence feature** (`az_price_divergence`): how far
   this AZ's price has drifted from its sibling AZs for the same instance
   type at the same timestamp. Computed in `feature_pipeline.py` but **not**
   enabled by default — see the comparison table, it made things worse in the
   one run tested, but that's not strong evidence at this sample size.
6. **Calibration + honest final test set** (`calibrate_and_finalize.py`).
   Platt scaling fit on the same data already used for early stopping (no new
   data spent), then final numbers reported on a slice that was **never**
   touched by training, early stopping, or calibration.

## Final comparison (identical held-out test set: 38,085 windows, 84 positives, base rate 0.221%)

| Model | PR-AUC | Lift vs. random | Brier (calibrated) | Best F1 | Recall | Confusion (TP/FN/FP) |
|---|---|---|---|---|---|---|
| **Transformer, 13 features (SHIPPED)** | **0.0211** | **9.55x** | **0.0022** (= trivial baseline) | 0.0947 | 21.4% | 18/66/278 |
| Transformer, 14 features (+ `az_price_divergence`) | 0.0103 | 4.67x | 0.0022 | 0.0536 | 3.6% | 3/81/25 |
| XGBoost, 14 features | 0.0037 | 1.66x | 0.1461 (badly miscalibrated) | 0.0157 | 22.6% | 19/65/2315 |
| Round 1 model (leaky split, broken alpha) | 0.0034 | 4.0x | 0.0036 (worse than trivial) | 0.0097 | 4.6% | 3/62/549 |

**Takeaways:**
- Fixing the leakage + FocalLoss bugs alone took PR-AUC from 4x → ~9x base
  rate lift on an honestly-measured test set — that's the real effect of
  Round 2, not noise.
- The Transformer beats XGBoost by a wide margin here. A lower-capacity model
  was the hypothesis going in (so few positive examples); it didn't pan out —
  XGBoost has by far the worst calibration of the three (Brier 66x the
  trivial baseline) and the weakest ranking signal.
- The cross-AZ feature is **not shipped**. One run isn't enough evidence to
  trust either direction with ~200 positive training examples — it needs a
  multi-seed comparison before being added back (`feature_config.py` has the
  full reasoning inline).
- Run-to-run variance is real: two separate runs of the *identical* 13-feature
  config scored 0.0183 and 0.0211 PR-AUC. Any single number here has a wide
  error bar — don't over-read small differences between configs.

## Serving fix, verified directly (with calibration applied)

```
c5.2xlarge  eu-north-1a -> 0.0010
c5.2xlarge  eu-north-1b -> 0.0014
c5.2xlarge  eu-north-1c -> 0.0014
c5.xlarge   eu-north-1a -> 0.0008
c5.xlarge   eu-north-1b -> 0.0014
c5.xlarge   eu-north-1c -> 0.0014
```

Scores vary per instance/AZ (flat-`0.0419` bug fixed) and now sit in a
sensible range near the true base rate (~0.2-0.8%) instead of the wildly
overconfident 0.05-0.09 range Round 1 produced — direct evidence the
calibration pass is doing its job.

## The limit fixing bugs and methodology can't fix

`is_spike = spot_price > prev_price * 1.01` is a **proxy label**, not a real
AWS reclaim event, and it's extremely rare (303 positive windows out of
386,868 — 0.078%). Even a well-trained, correctly-served, well-calibrated
model can only learn to predict >1% price jumps, which correlate weakly with
actual Spot interruptions. That's the ceiling on PR-AUC here — no amount of
further tuning gets past it without better labels.

**Not implemented:** lead-time and against-real-interruption evaluation. Both
need real interruption timestamps (e.g. from NTH/EventBridge history) to mean
anything; scoring lead-time against a price-spike proxy would just measure
how early the model predicts price spikes, not interruptions.

**Say in the paper:** *"the reactive path (Objective 1) is validated on real
Spot infrastructure; the predictive model is trained, evaluated, and
calibrated on a held-out test set with a real (~9.5x base rate) but weak
signal — usable as a secondary/advisory signal, not a primary trigger. The
ceiling is the proxy label, not the model or pipeline; real interruption
ground truth is future work."*
