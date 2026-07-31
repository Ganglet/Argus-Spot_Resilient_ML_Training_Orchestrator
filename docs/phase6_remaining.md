# Phase 6 — Remaining Work

Phase 6's **systems milestone is done**: the full migration chain is validated live on real EKS with IRSA (see `problems_and_decisions.md` → *Week 6 — Live Validation*). What remains before this is an ML4Sys-credible result, in three objectives.

| Objective | Owner | Gates |
|-------|-------|-------|
| 2. Benchmark harness + baselines | Person B | build now; final arm-4 numbers wait on Objective 3 |
| 3. Prediction model validation | Person B + Angshuman | **the scientific crux** — flat 0.0419 score |
| 1. Real Spot reclaim | Angshuman | needs a non-Free-Tier account |

**Order:** build Objective 2's harness + baselines now (no model needed) → fix Objective 3 → generate final table → Objective 1 for the "survived a real reclaim" claim.

---

## Objective 2 — Benchmark (Person B, start now)

### Objective
Produce the **results table + figures** quantifying whether *predictive* migration beats simpler baselines under Spot interruptions: completion, wasted compute, makespan, cost, recovery time. This is the paper's core evidence table.

### The 4 arms (share one training job)
1. **no-protection** — dies on interruption, restarts from epoch 0. Upper bound on waste.
2. **periodic checkpointing** — checkpoint every N steps regardless; resume from last. No signal.
3. **reactive-on-notice** — checkpoint only when the interruption arrives (SIGTERM / the free AWS 2-min notice). **This is the honest baseline to beat.**
4. **predictive (Argus)** — operator predicts risk → proactively checkpoints + migrates *before* the notice.

> The whole paper rides on arm 4 beating arm 3. Build it to reveal the truth, not to flatter — if predictive doesn't win, the numbers must show it (then we pivot the framing).

### Metrics (log per run, per arm)
- **Completion rate** (% jobs that finish) at a given interruption rate
- **Wasted compute** = training time between last usable checkpoint and interruption (the number that matters most)
- **Makespan** = wall-clock to finish
- **Checkpoint overhead** = count + time + storage
- **Recovery time** = interruption → training resumed
- **Cost** = $ for the makespan (spot vs on-demand rate × node-hours)
- **Lead time** (arm 4 only) = risk-trigger → actual interruption

### Interruption injection
- **Benchmark numbers use controlled injection**: a harness that kills the training pod on a **Poisson** schedule, mean rate matched to real Spot interruption frequency (pull real rates for the instance type from AWS Spot data). Run **many** interruptions across **many** repetitions — it's statistics, not one event.
- **Real reclaim (AWS FIS) is Objective 1**, a separate experiment. Do **not** couple the benchmark to real Spot — too slow/expensive for N trials, and the account is Free-Tier-restricted anyway.

### Experimental design
- Fix the training job + total work (CIFAR-10, fixed step budget).
- Sweep **interruption rate** (mean-time-between-interruptions ∈ {2, 5, 10, 30} min).
- Each **(arm × rate)**: **K ≥ 5** repetitions → mean ± std.
- Output: table (arm × rate → metrics) + figures (completion vs rate; wasted-compute by arm; makespan by arm).

### Critical practical fixes (we hit these on 2026-07-28 — do first)
1. **Cache the dataset.** Each pod re-downloads CIFAR-10 (~170 MB, 15-30 min) — fatal for N trials. **Bake it into the training image** (or a shared PVC/hostPath). Biggest time-saver.
2. **Fast config** so each trial is *minutes*: small model or capped batches/epoch. Measuring interruption behavior, not SOTA accuracy.
3. **Structured metric logging.** Prometheus isn't set up (Week 7). Emit **JSON-lines** from `train.py` + harness (epoch, step, wall-clock, checkpoint events, resume-from-epoch), then aggregate → CSV → table/plots. Don't scrape logs.
4. **No EKS/Spot needed for the benchmark.** Controlled injection runs on Minikube or one cheap node — the metrics only need *controlled* interruptions.

### Deliverable structure
```
benchmark/
  harness.py          # spawns a run, injects interruptions (Poisson), records timings
  arms/               # config per arm (no-protection, periodic, reactive, predictive)
  metrics_logger.py   # JSON-lines schema emitted by train.py + harness
  aggregate.py        # JSON-lines -> CSV -> table + figures
  results/            # CSV + figures
  README.md           # how to run + the results table
```

### Dependency
Arm 4's numbers are only meaningful once the model discriminates (Objective 3). **Arms 1-3 + the harness need no model — build them now**; they establish the baselines to beat.

---

## Objective 3 — Prediction model (DIAGNOSED 2026-07-30; two-step fix)

The flat `0.0419` was diagnosed — it's a **train/serve bug**, on top of an under-trained model + a weak proxy label. Root causes:
- **Bug #1 (direct cause):** training standardizes features per group (`dataset.py:51-52` StandardScaler) but the scaler is **discarded** (`train.py:96` saves only `state_dict`), and serving feeds **raw values** (`app.py`, no scaling). → OOD inputs → model collapses to the base rate `0.0419`.
- **Bug #2:** model trained only `epochs=3` ("just to verify loss drops", `train.py:58`).
- **Bug #3:** never evaluated — `val_loader` is built but **never used**; only `train_loss` logged. No AUC ever computed.
- **Bug #4 (secondary):** serving/training skew — `seq_len` 12 vs 24, `select_dtypes()` vs the 13 named columns.
- **Deeper limit:** the label is a proxy — `is_spike = spot_price > prev_price*1.01` (`dataset.py:38-40`), not real interruptions.

### Step 1 — Person B, FIRST: make the model actually work (uses current data)
Do these on the *existing* proxy labels — no new data needed:
1. **Persist + apply normalization.** Save the scaler (or switch to a fixed/global norm) and apply it at serving (`app.py`). *This alone un-flattens the output.*
2. **Align serving with training:** `seq_len` and the exact 13 feature columns (names + order).
3. **Train for real (»3 epochs) and EVALUATE** — wire up the unused `val_loader`: **PR-AUC** (not accuracy — rare events), **lead-time**, **calibration** on held-out data.

→ **Deliverable:** a working model + a **baseline PR-AUC on the current proxy labels**. This number decides everything (whether to improve, and prediction-led vs systems-led).

### Step 2 — Person B, ONLY IF Step 1's baseline is worth improving: upgrade to real labels
Real interruption labels are pulled + versioned in S3 (done, Angshuman):
```
s3://argus-feature-store-844641713781/labels/spot_interruption_labels_YYYY-MM-DD.csv
# regenerate/refresh:  python ml/data/pull_spot_advisor.py --upload-s3
```
These are **AWS Spot Instance Advisor interruption frequency per (type, region)** — real, but **aggregate** (a per-type rate, not a per-timestep event).
- **Option B (recommended):** add each type's real interruption rate as a **feature / prior** alongside the price time-series → keeps the transformer, grounds it in real AWS data instead of the price-spike proxy. Retrain, re-evaluate, **compare to the Step-1 baseline**.
- **Option A:** relabel the task to risk-tier classification — bigger change, drops the time-series framing.

### Framing decision — Angshuman, at the END (after the numbers exist)
Pick the strongest result for the 4-page poster:
- If Step 1/2 yields a real PR-AUC that **beats a reactive baseline** → **prediction-led**.
- Else → **systems-led** (Objective 1 + Week 6 are rock-solid) with prediction as preliminary/future work. Do **not** rest the headline on `0.0419`.
And answer the reviewer's killer question: *"why predict when AWS gives a free 2-min notice?"* — quantified (predictive loses < the 2-min reactive window, or pre-migrates to avoid it).

---

## Objective 1 — Survive a *real* Spot reclaim (Angshuman)

Currently the interruption is *simulated* via the operator's cordon+delete. To legitimately claim "survived a real reclaim":

1. **Non-Free-Tier account** with a **real Spot node group** (ML instance types). The current account only launches Free-Tier types — no Spot ever fulfills (P-013 / ADR-005).
2. **Wire the reactive path to the real signal.** The operator today reacts to a *predicted* risk score; a real reclaim is a different signal — the EventBridge `EC2 Spot Instance Interruption Warning`, or IMDS `/latest/meta-data/spot/instance-action`. Add **AWS Node Termination Handler** (easy win) or an EventBridge subscription so the node drains on the 2-min notice → pods get SIGTERM → `train.py`'s SIGTERM handler checkpoints → reschedule → resume.
3. **Trigger a deterministic real interruption** with **AWS Fault Injection Simulator**, action `aws:ec2:send-spot-instance-interruptions` — sends a genuine 2-min notice through the real path and reclaims the instance. This is the canonical, accepted way to test Spot resilience (not a simulation).

**Claim earned when:** real Spot node + NTH/EventBridge draining + FIS-triggered interruption → observed checkpoint → reschedule → resume. Until then, describe it precisely as "controlled interruption via cordon," never "survived Spot."

---

## Two gotchas when merging `week-6-eks`
- **`deploy.yml` fires on push to `main`** and runs `helm upgrade` against `argus-eks` — now torn down → **CI will fail.** Guard/disable that workflow before merging, or expect a red X.
- Keep `.terraform/` and `.terraform.tfstate.lock.info` gitignored (a lock file was accidentally committed once).
