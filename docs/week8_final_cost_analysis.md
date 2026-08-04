# Week 8 — Final Cost Analysis

Consolidates the cost-vs-On-Demand data already computed in
`docs/objective2_result.md` (Week 7) into one standalone reference, and
extrapolates it to a realistic job duration so the percentages translate
into an actual dollar figure worth citing.

## Method

`benchmark/aggregate.py` computes, per trial:

- `cost_usd` = actual makespan (wall-clock, including any wasted-restart
  overhead) × a placeholder Spot rate ($0.058/hr)
- `cost_on_demand_usd` = `step_budget × step_time_sec` (the time an
  On-Demand instance — never interrupted, no restart overhead — would take)
  × `c5.xlarge`'s real eu-north-1 On-Demand rate ($0.188/hr, same instance
  type Objective 1's real Spot node used)
- `cost_savings_vs_ondemand_pct` = `(1 − cost_usd / cost_on_demand_usd) × 100`

This answers the actual question a cost analysis needs to: does Spot's
hourly discount survive interruption/checkpoint overhead, or does a bad
policy eat the savings?

## Savings by arm and rate (80-trial sweep, Week 7)

| Arm | 120s | 300s | 600s | 1800s |
|---|---:|---:|---:|---:|
| no-protection | 25.6% | 64.4% | 67.9% | 66.0% |
| periodic | 67.3% | 67.9% | 68.1% | **68.2%** |
| reactive | 32.5% | 64.4% | 67.9% | 66.0% |
| **predictive** | 27.4% | 61.8% | 67.5% | **68.8%** |

Periodic is the most cost-stable arm (67-68% at every rate — fixed
checkpoint cadence, doesn't react to how often interruptions actually
happen). Predictive reaches the single best savings figure at slow rates
(68.8% at 1800s) but drops to 27.4% at the fastest rate — the same
checkpoint-overhead cost documented in `objective2_result.md`'s Week 7
section (221.6 checkpoints in one run at rate=120s).

## What this means in real dollars

The benchmark's `step_budget=500` synthetic job takes ~2.5 minutes
uninterrupted — too short to cite a dollar figure anyone would recognize.
Scaling the same *percentages* (which are what the benchmark actually
measures — they're rate-independent of job length) to a realistic training
duration:

| Job length | On-Demand cost | Predictive, typical rate (68.8%) | Predictive, worst case (27.4%, rate=120s) |
|---|---:|---:|---:|
| 1 hour | $0.19 | $0.06 (**saved $0.13**) | $0.14 (**saved $0.05**) |
| 10 hours | $1.88 | $0.59 (**saved $1.29**) | $1.37 (**saved $0.52**) |
| 24 hours | $4.51 | $1.41 (**saved $3.10**) | $3.28 (**saved $1.24**) |

**Read the range, not one number**: at realistic interruption rates
(≥300s MTBF — 5+ minutes between interruptions, which is closer to typical
Spot behavior than the 120s worst case), predictive/periodic both land
around **62-69% savings vs. On-Demand** — for a 24-hour job, roughly **$3 of
$4.51 saved**. At the aggressive 120s worst case, savings shrink to
**~27-33%** across every signal-based arm (predictive, reactive), because
checkpoint/notice overhead starts competing with the Spot discount itself.

## Honest scope

- The $0.058/hr Spot rate is the benchmark's placeholder (`aggregate.py`,
  never swapped for a live-quoted rate — see `ADR-005` in
  `docs/problems_and_decisions.md` on why the account never ran a
  Spot-priced node group). The **percentage savings are the real result**;
  the absolute dollar figures above are illustrative, scaled from that
  placeholder rate, not a live AWS billing capture.
- These figures come from the synthetic benchmark job
  (`benchmark/job.py`), not a real multi-hour CIFAR-10 run — consistent
  with the benchmark's own scope (`docs/phase6_remaining.md`: "measuring
  interruption behavior, not SOTA accuracy").
- See `docs/objective2_result.md` for the full 80-trial results this is
  built from, and `docs/week8_stress_test.md` for cost behavior under 3
  concurrent jobs.
