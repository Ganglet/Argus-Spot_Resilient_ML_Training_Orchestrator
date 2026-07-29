# Track 2 — Benchmark harness

Owner: Person B (`docs/phase6_remaining.md` Track 2). Produces the results
table + figures comparing four checkpoint policies under controlled,
Poisson-scheduled interruptions:

| Arm | `checkpoint_mode` | Behavior |
|-----|--------------------|----------|
| 1. no-protection | `none` | Never checkpoints. Every interruption restarts at step 0. |
| 2. periodic | `periodic` | Checkpoints every N steps, no signal awareness. |
| 3. reactive-on-notice | `reactive` | Checkpoints only when the (simulated) 2-min interruption notice arrives. The baseline to beat. |
| 4. predictive (Argus) | `predictive` | Checkpoints + migrates on an earlier, predicted risk signal, ahead of the notice. |

All four arms run the exact same training job (`job.py`, same CNN as
`ml/cifar10_job/train.py`) — only the checkpoint policy config in `arms/*.json`
differs, per the spec's "share one training job" requirement.

## How it works

- **`job.py`** runs the training loop for one arm. `reactive`/`predictive`
  poll for a `NOTICE`/`RISK` trigger *file* in the run dir once per step and
  checkpoint when one appears, then delete it. This mirrors the production
  operator's S3 `_FLUSH_TRIGGER` marker-polling design (see
  `docs/B5_cifar10_checkpointing.md`) instead of relying on OS signals, so it
  behaves identically on every dev machine / CI runner.
- **`harness.py`** spawns `job.py`, samples interruption instants from a
  Poisson process (mean = `--rates`, in seconds), and at each instant drops
  the arm's configured trigger file(s) ahead of a kill+respawn — respawned
  against the same run dir so any checkpoint persists. No EKS/Minikube/Spot
  needed; this runs as local subprocesses so hundreds of trials stay cheap
  (per the spec: "No EKS/Spot needed for the benchmark").
- **`aggregate.py`** reads every run's `events.jsonl` (job telemetry) +
  `harness.jsonl` (interruption record), computes completion rate, wasted
  compute, makespan, checkpoint overhead, recovery time, cost, and (for the
  predictive arm) lead time, then writes `results/summary_runs.csv`,
  `results/summary_table.csv`, and `results/figures/*.png`.

## Running it

```bash
# Smoke test (seconds-scale, synthetic data, ~a minute or two total):
python benchmark/harness.py --arms no-protection,periodic,reactive,predictive \
    --rates 15,40 --reps 2 --step-budget 400 --step-time-sec 0.02

# Full sweep (production-scale rates: {2,5,10,30} min, matching real Spot
# interruption frequency; K=5 reps per arm x rate; runs for a while):
python benchmark/harness.py --reps 5 --step-budget 2000 --step-time-sec 0.3

python benchmark/aggregate.py
```

Results land in `results/summary_table.csv` (the paper's core table) and
`results/figures/`.

## Design notes / known constraints

- **Cold start dominates at very high interruption rates.** Each respawn
  pays Python + torch import cost (~4s on this dev machine). That's
  negligible at the real Spot-matched rates (minutes), but a smoke test with
  a mean interruption rate close to that cold-start cost will show
  unrealistic thrashing (e.g. `no-protection` timing out) — not a harness
  bug, just cold start dominating at a rate the harness was never meant to
  run at. Keep `--rates` well above ~10s for meaningful results, and scale
  `--step-budget` / `--step-time-sec` so an uninterrupted run is the same
  order of magnitude as the interruption rate (see "Fast config" in
  `docs/phase6_remaining.md`).
- **`notice_lead_seconds` / `risk_lead_seconds` must be smaller than the
  interruption rate being tested**, or the arm degenerates: with a fixed
  120s notice lead and a 6s mean interruption rate, the harness (correctly)
  fires the notice at essentially T=0 every cycle, so `reactive` gets exactly
  one early checkpoint per respawn and then runs unprotected until whatever
  (occasionally large) T the Poisson draw picked — inflating wasted compute.
  This is faithful to reality (AWS's notice is a fixed 120s-before-reclaim
  offset, not a recurring signal) — it's just not a meaningful regime to
  benchmark. The production rate sweep ({2,5,10,30} min) keeps the 120s
  notice lead sane by construction; only watch for this if testing custom
  rates below a few minutes.
- **Data:** defaults to a synthetic CIFAR-10-shaped dataset (random tensors)
  so the harness needs no dataset download and measures interruption
  behavior, not accuracy, per the Track 2 spec. Pass no `--synthetic` flag
  and ensure `torchvision` + the real CIFAR-10 cache are available to use
  real data for final numbers.
- **`predictive`'s `risk_lead_seconds`** (`arms/predictive.json`) is a
  placeholder until Track 3 fixes the flat 0.0419 model score and supplies a
  real measured lead time.
- **Cost** uses a placeholder spot hourly rate (`SPOT_HOURLY_RATE_USD` in
  `aggregate.py`) — swap for the real rate of whatever instance type the
  final run uses.

## Deliverable structure

```
benchmark/
  job.py              # shared training job, 4 checkpoint policies
  harness.py           # spawns runs, injects Poisson interruptions, records timings
  metrics_logger.py    # JSON-lines schema shared by job.py + harness.py
  aggregate.py          # JSON-lines -> CSV -> table + figures
  arms/                 # one config per arm
  results/              # summary_runs.csv, summary_table.csv, figures/
```
