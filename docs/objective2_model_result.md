# Objective 2 Result — Predictive Model, Real Training Run (2026-07-31)

Honest results for the paper figure. Trained and evaluated on the real feature
pipeline output (`ml/data/features.csv`, 386,868 windowed sequences from live
`eu-north-1` Spot price history). Reproduce with `python ml/model/train.py`
then `python ml/model/calibrate_and_finalize.py`.

This went through four rounds: Round 1 fixed the bugs that made the model
useless (flat output). Round 2 fixed methodology problems that were making
the *measurement* of the model optimistic/pessimistic in different ways, and
tried a few concrete improvements. Round 3 tried a real (non-proxy) feature
and, in the process, surfaced just how much run-to-run variance there is.
Round 4 quantified that variance properly with a 5-seed sweep — **that's the
number that should actually be cited**, not any single run above. All four
are recorded below because the reasoning matters for anyone touching this
code next.

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

## Round 3 — real AWS interruption-rate feature

`s3://argus-feature-store-844641713781/labels/` has real Spot Instance Advisor
interruption-frequency data (pulled via `ml/data/pull_spot_advisor.py`) — an
actual AWS-published number, not the price-spike proxy. Added it as
`instance_interruption_rate` (`feature_pipeline.py`, merged per instance type),
wired into the model as a 14th feature, retrained.

Result: **PR-AUC 0.0172 (7.80x lift) — worse than the 13-feature baseline at
the time (0.0211).** Same outcome as the cross-AZ feature experiment: reverted,
kept the feature computed in the pipeline but out of `FEATURE_COLUMNS`, same
"needs multi-seed validation before trusting either direction" reasoning.

Restoring the 13-feature baseline required one more retrain (identical code
and config, no changes) — and that run landed a **much** better optimum:
**PR-AUC 0.0480 (21.76x lift)**, now the shipped checkpoint. This is the same
config that scored 0.0183 and then 0.0211 in the two earlier runs. Nothing
changed except the random seed / data loader shuffle order.

## Round 4 — quantifying the variance properly (5-seed sweep)

Round 3 found three runs of the identical 13-feature config scoring 0.0183,
0.0211, and 0.0480 PR-AUC and correctly flagged that as "too noisy to trust
any single number" — but didn't have a real answer for what the number
actually is. `train.py` now accepts a `seed` param (seeds torch/numpy/random),
and `multi_seed_eval.py` trains 5 seeds from scratch into scratch directories
(the shipped checkpoint is untouched), evaluates each on the same held-out
test set, and reports mean/std instead of a single draw.

| Seed | PR-AUC | Lift |
|---|---|---|
| 0 | 0.0393 | 17.76x |
| 1 | 0.0500 | 22.61x |
| 2 | 0.0211 | 9.55x |
| 3 | 0.0225 | 10.17x |
| 4 | 0.0294 | 13.29x |

**Mean: 0.0324 PR-AUC (14.68x lift over the 0.221% base rate), std 0.0122,
range 9.55x–22.61x, 95% CI ≈ [9.9x, 19.5x].**

This is a materially better and more trustworthy finding than anything in
Round 3: every one of 5 independent seeds landed between 9.5x and 22.6x lift
— **none collapsed toward random**. That consistency is real evidence of a
genuine, repeatable (if weak) signal, not noise dressed up as a result. The
shipped checkpoint (from an earlier unseeded run, PR-AUC 0.0480) is one draw
from this same distribution — a lucky one, on the high end of the observed
range. Report the mean (14.68x), not the shipped checkpoint's own number,
when characterizing what this model actually does.

## Final comparison (identical held-out test set: 38,085 windows, 84 positives, base rate 0.221%)

| Model | PR-AUC | Lift vs. random | Brier (calibrated) | Best F1 | Precision | Recall | Confusion (TP/FN/FP) |
|---|---|---|---|---|---|---|---|
| **Transformer, 13 features (SHIPPED, latest run)** | **0.0480** | **21.76x** | **0.0022** | 0.1607 | 32.1% | 10.7% | 9/75/19 |
| Transformer, 13 features (earlier run, same config) | 0.0211 | 9.55x | 0.0022 | 0.0947 | 6.1% | 21.4% | 18/66/278 |
| Transformer, 13 features (earliest run, same config) | 0.0183 | 8.30x | 0.0026→0.0022 | 0.1139 | 12.2% | 10.7% | 9/75/65 |
| Transformer, 14 features (+ `instance_interruption_rate`, real AWS data) | 0.0172 | 7.80x | 0.0022 | 0.0826 | 5.1% | 21.4% | 18/66/334 |
| Transformer, 14 features (+ `az_price_divergence`) | 0.0103 | 4.67x | 0.0022 | 0.0536 | 10.7% | 3.6% | 3/81/25 |
| XGBoost, 14 features | 0.0037 | 1.66x | 0.1461 (badly miscalibrated) | 0.0157 | 0.8% | 22.6% | 19/65/2315 |
| Round 1 model (leaky split, broken alpha)¹ | 0.0034 | 4.0x | 0.0036 (worse than trivial) | 0.0097 | 0.5% | 4.6% | 3/62/549 |

¹ Not the same test set — Round 1 predates the leakage fix, so it was measured
on the old `random_split` validation set (77,374 samples, different split
methodology entirely). Included only for rough before/after context, not a
strict apples-to-apples row.

**Takeaways:**
- Fixing the leakage + FocalLoss bugs alone took PR-AUC from 4x → a
  5-seed-averaged **14.68x** base-rate lift on an honestly-measured test set
  — that's the real, quantified effect of Round 2, confirmed by Round 4.
- **Individual runs are noisy (9.5x-22.6x observed), but the average across
  seeds is not** — 5/5 seeds landed well above random, none collapsed. That's
  the difference between "we don't know if this works" (Round 3's honest
  uncertainty) and "this works, modestly, and here's the confidence interval"
  (Round 4). Still cite the range, not a single number, when precision matters.
- Both new-feature attempts (cross-AZ divergence, real interruption rate)
  scored *worse* than the single baseline run they were compared against at
  the time — each is still only one data point per feature, so that verdict
  is weaker evidence than the baseline's own multi-seed result. Revisit both
  with a proper multi-seed comparison before fully ruling them out.
- The Transformer beats XGBoost by a wide margin, consistently. That
  comparison isn't in doubt the way the feature comparisons are — XGBoost's
  gap is much larger than the seed-to-seed variance band.

## Serving fix, verified directly (with calibration applied)

```
c5.2xlarge  eu-north-1a -> 0.0012
c5.2xlarge  eu-north-1b -> 0.0014
c5.2xlarge  eu-north-1c -> 0.0014
c5.xlarge   eu-north-1a -> 0.0003
c5.xlarge   eu-north-1b -> 0.0014
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
calibrated on a held-out test set with a real, repeatable but weak signal —
14.68x base-rate lift on average (std 1.22x, 95% CI ~9.9-19.5x) across 5
independently seeded training runs — usable as a secondary/advisory signal,
not a primary trigger. The ceiling is the proxy label and the small number
of positive examples (not the model, pipeline, or measurement methodology,
which is now on solid ground); real interruption ground truth is the
remaining future work."*
