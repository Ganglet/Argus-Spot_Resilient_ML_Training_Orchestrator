# Objective 2 Result — Predictive Model, Real Training Run (2026-07-31)

Honest results for the paper figure. Trained and evaluated on the real feature
pipeline output (`ml/data/features.csv`, 386,868 windowed sequences from live
`eu-north-1` Spot price history). Reproduce with `python ml/model/train.py`
then `python ml/model/evaluate.py`.

## What was actually broken

The model previously returned a **flat `0.0419` for every instance type/AZ**
(see `problems_and_decisions.md` P-018/019). Root causes, all fixed on this
branch:

1. **Train/serve skew (the direct cause of the flat score).** Training
   standardized features with `StandardScaler`, fit *per instance/AZ group*,
   then threw the scaler away (`dataset.py`). Serving (`app.py`) fed the model
   raw `spot_price`/`rolling_std` values with no scaling at all. A model
   trained on ~N(0,1) inputs, fed raw ones (`spot_price≈0.05`,
   `rolling_std≈0.001`), saturates to a near-constant output. Fixed by fitting
   **one global scaler**, persisting it (`spot_scaler.joblib`), and applying
   it at serving.
2. **3-epoch smoke test, never scaled up.** `train.py` hardcoded `epochs = 3`
   with a comment admitting it was "just for verifying loss drops," and never
   touched the validation loader it built. Fixed: real validation loop
   (loss + PR-AUC every epoch) with early stopping on val loss.
3. **Serving feature/sequence mismatch.** Training used 13 named columns in a
   fixed order and `seq_length=24`; serving used `select_dtypes()` (no
   guaranteed column order) and `seq_len=12`. Fixed by pulling both into a
   single `feature_config.py` imported by both training and serving, plus a
   metadata file (`model_metadata.json`) that serving validates against at
   startup.
4. **(Found while fixing #2) MLflow tracking URI crashed on Windows.**
   `train.py` passed a raw filesystem path to `mlflow.set_tracking_uri()`,
   which threw `UnsupportedModelRegistryStoreURIException` before a single
   batch ran — every prior "training run" had actually been silently dying at
   this line. Switched to the SQLite backend already used by
   `hyperparameter_tune.py` (see `B3_model_training.md`).

## Real training run

12 epochs, early-stopped (no val-loss improvement for 5 epochs), ~55 min
total on CPU. `d_model=128, nhead=2, num_layers=2, lr=5e-4` — the config
`hyperparameter_tune.py`'s grid search already found best.

| Epoch | Train Loss | Val Loss | Val PR-AUC |
|-------|-----------|----------|------------|
| 1 | 0.0017 | 0.0017 | 0.0063 |
| 7 (**best, checkpointed**) | — | **0.00134** | 0.0028 |
| 10 | 0.0015 | 0.0014 | 0.0029 |
| 12 (stopped) | 0.0015 | 0.0013 | 0.0033 |

Best checkpoint selected on val loss (epoch 7) — the metric early stopping
actually tracks. PR-AUC bounces around a fixed small range regardless of
epoch, for reasons explained below.

## Evaluation on held-out validation data

```
Total Validation Samples: 77,374
Total Interruption Events (1s) in Val: 65
PR-AUC (Average Precision): 0.0034
Brier Score (calibration):  0.0036
Optimal Probability Threshold: 0.1090
F1-Score: 0.0097  |  Precision: 0.0054  |  Recall: 0.0462

Confusion Matrix @ optimal threshold:
                  Predicted Safe   Predicted Risk
Actual Safe            76,760            549
Actual Risk                62              3
```

**Read this honestly, not optimistically:** the validation base rate is
65 / 77,374 = 0.084%. A model with *zero* signal would score PR-AUC ≈ 0.00084.
This model scores 0.0034 — roughly **4x the base rate**, i.e. a real but weak
signal, not a strong discriminator.

The Brier score is worse than it looks: a trivial model that always predicts
"safe" (~0) gets Brier ≈ 0.00084 on this base rate. This model gets **0.0036
— over 4x worse than that trivial baseline.** That means it is systematically
over-predicting risk (its outputs sit around 0.05–0.09 rather than near-0),
not well-calibrated at the low end as a first read might suggest. Most likely
cause: Focal Loss optimizes for ranking rare positives, not calibrated
probabilities, and a single global scaler averages over instance types with
very different absolute price scales. If calibrated probabilities matter for
the paper's threshold-setting story, that needs a calibration pass (Platt
scaling / isotonic regression) on top of this checkpoint — not done here.

## Serving fix, verified directly

Called `_predict()` for 8 different (instance_type, AZ) pairs against the
retrained model — scores now vary per instance/AZ instead of returning the
same constant:

```
c5.2xlarge  eu-north-1a -> 0.0685
c5.2xlarge  eu-north-1b -> 0.0913
c5.2xlarge  eu-north-1c -> 0.0785
c5.xlarge   eu-north-1a -> 0.0710
c5.xlarge   eu-north-1b -> 0.0693
c5.xlarge   eu-north-1c -> 0.0796
g4dn.xlarge eu-north-1a -> 0.0719
g4dn.xlarge eu-north-1b -> 0.0669
```

The flat-`0.0419`-for-everything bug is confirmed fixed.

## The limit fixing bugs can't fix

`is_spike = spot_price > prev_price * 1.01` is a **proxy label**, not a real
AWS reclaim event, and it's extremely rare (303 positive windows out of
386,868 — 0.078%). Even a perfectly trained, correctly-served model can only
learn to predict >1% price jumps, which correlate weakly with actual Spot
interruptions. That's why PR-AUC stays low regardless of epoch count or
architecture — this is a data/label problem, not a training bug.

**Not implemented here:** lead-time and against-real-interruption evaluation.
Both need real interruption timestamps (e.g. from NTH/EventBridge history) to
mean anything; scoring lead-time against a price-spike proxy would just be
measuring how early the model predicts price spikes, not interruptions.

**Say in the paper:** *"the reactive path (Objective 1) is validated on real
Spot infrastructure; the predictive model's serving bug is fixed and it is
trained/evaluated honestly, but it currently shows only weak discrimination
(PR-AUC ≈ 4x base rate) because ground-truth interruption labels are not yet
available — this is future work, not a claim made in this paper."*
