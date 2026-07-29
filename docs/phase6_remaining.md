# Phase 6 — Remaining Work

Phase 6's **systems milestone is done**: the full migration chain is validated live on real EKS with IRSA (see `problems_and_decisions.md` → *Week 6 — Live Validation*). What remains before this is an ML4Sys-credible result, in three tracks.

| Track | Owner | Gates |
|-------|-------|-------|
| 2. Benchmark harness + baselines | Person B | build now; final arm-4 numbers wait on Track 3 |
| 3. Prediction model validation | Person B + Angshuman | **the scientific crux** — flat 0.0419 score |
| 1. Real Spot reclaim | Angshuman | needs a non-Free-Tier account |

**Order:** build Track 2's harness + baselines now (no model needed) → fix Track 3 → generate final table → Track 1 for the "survived a real reclaim" claim.

---

## Track 2 — Benchmark (Person B, start now)

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
- **Real reclaim (AWS FIS) is Track 1**, a separate experiment. Do **not** couple the benchmark to real Spot — too slow/expensive for N trials, and the account is Free-Tier-restricted anyway.

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
Arm 4's numbers are only meaningful once the model discriminates (Track 3). **Arms 1-3 + the harness need no model — build them now**; they establish the baselines to beat.

---

## Track 3 — Prediction model validation (the scientific crux)

The predict-service returned a **flat 0.0419 risk for every instance type/AZ** during the live run. Until this is understood and fixed, the "predictive" claim does not hold. Steps in order:

1. **Diagnose the flat score — bug or dead model?** Identical output for every input is a red flag. Check: is the model actually loaded (not a fallback constant)? Are features distinct per input, or does everything collapse to one vector? A model outputting the base rate for everything is underfit/collapsed (common with rare-event data + Focal Loss).
2. **Get labeled interruption ground truth.** Can't claim "predicts interruptions" without knowing when they actually happened. Spot price alone is a weak proxy — source AWS Spot interruption/rebalance signals as labels. The feature store is stale (April 2026); refresh it.
3. **Evaluate properly:** **PR-AUC** (not accuracy — interruptions are rare), **lead time** (minutes before reclaim that risk crosses threshold — this *is* the value), **calibration**.
4. **Answer the killer reviewer question up front:** *"Why predict, when AWS gives a free 2-minute notice?"* Novelty rides on this. The answer must be quantified: predictive checkpointing loses **< the 2-min reactive window**, or pre-migrates to avoid the reclaim. If it can't beat arm 3 (reactive), the predictive claim doesn't hold.

**If the model is genuinely flat and unfixable in time:** pivot to a *systems* contribution — the orchestrator + live-EKS migration — with prediction as future work. Do not rest the central claim on 0.0419.

---

## Track 1 — Survive a *real* Spot reclaim (Angshuman)

Currently the interruption is *simulated* via the operator's cordon+delete. To legitimately claim "survived a real reclaim":

1. **Non-Free-Tier account** with a **real Spot node group** (ML instance types). The current account only launches Free-Tier types — no Spot ever fulfills (P-013 / ADR-005).
2. **Wire the reactive path to the real signal.** The operator today reacts to a *predicted* risk score; a real reclaim is a different signal — the EventBridge `EC2 Spot Instance Interruption Warning`, or IMDS `/latest/meta-data/spot/instance-action`. Add **AWS Node Termination Handler** (easy win) or an EventBridge subscription so the node drains on the 2-min notice → pods get SIGTERM → `train.py`'s SIGTERM handler checkpoints → reschedule → resume.
3. **Trigger a deterministic real interruption** with **AWS Fault Injection Simulator**, action `aws:ec2:send-spot-instance-interruptions` — sends a genuine 2-min notice through the real path and reclaims the instance. This is the canonical, accepted way to test Spot resilience (not a simulation).

**Claim earned when:** real Spot node + NTH/EventBridge draining + FIS-triggered interruption → observed checkpoint → reschedule → resume. Until then, describe it precisely as "controlled interruption via cordon," never "survived Spot."

---

## Two gotchas when merging `week-6-eks`
- **`deploy.yml` fires on push to `main`** and runs `helm upgrade` against `argus-eks` — now torn down → **CI will fail.** Guard/disable that workflow before merging, or expect a red X.
- Keep `.terraform/` and `.terraform.tfstate.lock.info` gitignored (a lock file was accidentally committed once).
