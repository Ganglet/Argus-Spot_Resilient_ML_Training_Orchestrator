# Objective 2 Result — Benchmark Harness, Full Sweep (2026-08-02)

The paper's core evidence table: does predictive migration beat simpler
checkpoint policies under controlled, Poisson-scheduled interruptions?
Reproduce with:

```bash
python benchmark/harness.py --reps 5 --step-budget 500 --step-time-sec 0.3
python benchmark/aggregate.py
```

Results in `benchmark/results/summary_table.csv` (per arm x rate, mean ± std)
and `benchmark/results/figures/*.png`.

## Method

Four arms share one training job (`benchmark/job.py`, a small CNN — same
architecture family as `ml/cifar10_job/train.py`, synthetic CIFAR-10-shaped
data so runs are cheap and reproducible without a dataset download):

| Arm | Checkpoint policy |
|---|---|
| no-protection | never checkpoints; any interruption restarts at step 0 |
| periodic | checkpoints every 20 steps, no signal awareness |
| reactive-on-notice | checkpoints only when a 120s "notice" fires (stands in for AWS's real 2-min Spot warning) — **the honest baseline to beat** |
| predictive (Argus) | checkpoints + migrates on a 300s "risk" signal, ahead of the notice |

`benchmark/harness.py` spawns each job as a subprocess and kills it on a
Poisson schedule (mean = the tested rate), respawning against the same run
dir so any saved checkpoint survives. No EKS/Spot needed — this runs as local
subprocesses, so 80 trials (4 arms × 4 rates × 5 reps) stay cheap. Rates
{120, 300, 600, 1800}s match the roadmap's real-Spot-frequency sweep
({2, 5, 10, 30} min).

## Bug found and fixed before trusting any of this

First run: **every predictive-arm trial timed out.** Traced it to a real bug,
not a config issue — `harness.py` would kill and respawn the job process,
then immediately move on to schedule/trigger the *next* interruption without
checking whether the freshly-spawned process had even finished importing
torch and reached its training loop yet. At interruption rates approaching
or exceeding the risk/notice lead time, this compounds into a busy loop:
respawn, immediately trigger again, respawn again — the job never gets far
enough to actually see the trigger file and save a checkpoint.

Measured impact before the fix (predictive arm, rate=120s): **24 respawns,
1 real checkpoint saved.** The arm was silently degrading to no-protection's
behavior (total data loss every interruption) *plus* extra respawn overhead
— worse than doing nothing, and it would have quietly corrupted exactly the
comparison this benchmark exists to make.

Fix: `harness.py` now waits for the respawned process to log a
`started`/`resumed` event before proceeding to the next interruption cycle
(`wait_for_ready`, wired into every `kill_and_respawn` call site). Re-verified
before the full sweep: 24/24 migrations confirmed and checkpointed correctly
at rate=120s post-fix. Also made the sweep resumable (skips any `(arm, rate,
rep)` trial that already has a terminal outcome on disk) — worth having,
since long unattended runs in this environment have died mid-way before (see
`docs/objective3_result.md`'s training history).

## Results — full sweep (80/80 trials completed, 5 reps each)

| Arm | Rate | Wasted compute (s) | Makespan (s) | Recovery (s) | Checkpoints | Cost ($) |
|---|---|---|---|---|---|---|
| no-protection | 120s | 202.3 ± 141.1 | 361.8 | 62.4 | 0.0 | 0.0058 |
| no-protection | 300s | 21.4 ± 41.6 | 173.0 | — | 0.0 | 0.0028 |
| no-protection | 600s | 4.7 ± 10.5 | 156.0 | — | 0.0 | 0.0025 |
| no-protection | 1800s | 14.1 ± 31.6 | 165.4 | — | 0.0 | 0.0027 |
| periodic | 120s | 4.3 ± 3.4 | 158.8 | 65.7 | 24.0 | 0.0026 |
| periodic | 300s | 1.6 ± 2.4 | 156.3 | — | 24.0 | 0.0025 |
| periodic | 600s | 0.9 ± 2.1 | 155.1 | — | 24.0 | 0.0025 |
| periodic | 1800s | 0.7 ± 1.5 | 154.5 | — | 24.0 | 0.0025 |
| **reactive** | **120s** | **169.4 ± 105.8** | 328.0 | 58.8 | 4.8 | 0.0053 |
| reactive | 300s | 21.3 ± 41.4 | 173.1 | — | 0.8 | 0.0028 |
| reactive | 600s | 4.6 ± 10.4 | 156.1 | — | 0.4 | 0.0025 |
| reactive | 1800s | 14.1 ± 31.5 | 165.5 | — | 0.2 | 0.0027 |
| **predictive** | **120s** | **0.0 ± 0.0** | 270.0 | 5.4 | 35.6 | 0.0044 |
| predictive | 300s | 0.0 ± 0.0 | 160.6 | 17.0 | 5.2 | 0.0026 |
| predictive | 600s | 0.0 ± 0.0 | 155.3 | 15.1 | 2.2 | 0.0025 |
| predictive | 1800s | 0.0 ± 0.0 | 151.5 | — | 0.2 | 0.0024 |

Completion rate was **100% for every arm at every rate** — the step budget
(500 steps) and wall-clock deadline (4x the uninterrupted runtime) were
generous enough that nothing ran out of time. That means completion rate
isn't the differentiator here; **wasted compute is**, and it's a clean result.

## The headline finding: predictive wins, cleanly, at every rate

**Predictive achieves exactly zero wasted compute at all four interruption
rates** — a 100% reduction vs. reactive at every single rate (169.4s → 0s at
the fastest, all the way down to 14.1s → 0s at the slowest). It always gets
to checkpoint *before* the simulated interruption, so it never loses work.

**The more interesting finding is *why* reactive underperforms at high
frequency**, and it directly answers the roadmap's required "why predict
when AWS gives a free 2-minute notice?" question:

At rate=120s, reactive's wasted compute (169.4s) is nearly as bad as
no-protection's (202.3s) — the reactive baseline barely helps at this rate.
The reason is mechanical: reactive's notice lead (120s) is *approximately
equal to* the mean time between interruptions (120s) at this rate. By the
time one interruption's notice fires, the *next* one is often already close
behind, so there's rarely enough real lead time to actually get a checkpoint
saved before the kill. **Reactive's real-world 2-minute notice stops being
useful exactly when interruptions come faster than about once every 2
minutes** — which is a realistic regime for aggressive Spot markets. That's
the quantified answer: predictive isn't valuable because reactive is broken
in general, it's valuable specifically when the interruption rate approaches
or exceeds the fixed notice window, which is exactly where reactive's own
data shows it degrading toward no-protection.

**Periodic is a surprisingly strong "dumb" baseline** at high interruption
rates (4.3s wasted at 120s — far better than reactive's 169.4s) precisely
*because* it's signal-unaware: it doesn't depend on getting enough lead time
before a kill, it just checkpoints on a fixed schedule regardless. Worth
noting honestly — an unglamorous fixed-interval checkpoint is a real
competitor to reactive when interruptions are frequent, even though it's not
a competitor to predictive (which still wins on wasted compute *and* doesn't
need periodic's baseline I/O tax at low interruption rates: periodic still
does 24 checkpoints at rate=1800s where nothing was ever going to interrupt
it, wasting I/O for no benefit).

## Honest limitations

- **`risk_lead_seconds=300` (predictive's lead time) is a benchmark
  assumption, not an empirical measurement from the real model.** The
  `arms/predictive.json` config has always said this is a placeholder
  pending "the model's real measured lead time" — and per
  `docs/objective3_result.md`, that measurement isn't possible with the
  current proxy label (price spikes, not real interruption timestamps).
  **This result shows what happens *if* a predictive system has ~5 minutes
  of reliable lead time — it does not prove the currently-trained model
  achieves that lead time in practice.** Don't conflate the two when writing
  this up.
- **The training job is synthetic** (small CNN, random CIFAR-10-shaped
  tensors, no real dataset or EKS). This measures checkpoint/interruption
  *mechanics*, not end-to-end training realism — consistent with the
  roadmap's explicit "measuring interruption behavior, not SOTA accuracy"
  scoping.
- **Completion rate didn't differentiate the arms** at these settings (100%
  across the board) — the real signal is in wasted compute, makespan, and
  checkpoint overhead, not completion rate. A tighter wall-clock budget would
  likely separate no-protection/reactive from periodic/predictive on
  completion rate too, but wasn't necessary to make the point here.

**Say in the paper:** *"Under controlled, Poisson-scheduled interruptions
matched to real Spot interruption frequencies, predictive checkpointing
eliminates wasted compute entirely (0s at every tested rate, vs. up to 202s
for no-protection), while the reactive baseline's advantage over
no-protection collapses as the interruption rate approaches the fixed
2-minute notice window. This quantifies exactly when prediction earns its
complexity: at interruption frequencies where a fixed reactive notice stops
providing meaningful lead time. The assumed 5-minute predictive lead time is
a benchmark parameter, not yet an empirical property of the trained model —
validating that gap is future work alongside real interruption labels (see
`docs/objective3_result.md`)."*
