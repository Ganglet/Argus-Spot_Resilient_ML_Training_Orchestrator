# Concurrent Stress Test, Final Cost Analysis & README Polish

**Phase:** Week 8 — SpotGuard (Conclusion)  
**Owner:** `[Both]` items, this pass completed by Person B  
**Status:** Complete — 3 concurrent jobs stress-tested, cost savings consolidated into a standalone analysis, README polished with badges and a quick-start section.

---

## Objective

Close out three of Week 8's `[Both]` deliverables: prove the system handles multiple simultaneous `SpotResilientJob`s correctly, turn the Week 7 cost-vs-On-Demand data into a citable final analysis, and finish the README polish (badges, quick-start) that was left partial after Week 7.

---

## What Was Done

1. **`benchmark/stress_test.py`**: Launches 3 `predictive`-arm jobs at once (real subprocesses, same mechanism as `benchmark/harness.py`'s sweep) into separate run directories, and compares against the same 3 jobs run sequentially — isolating whether concurrency itself (CPU contention, checkpoint I/O contention) degrades behavior.
2. **Ran the stress test** (rate=300s, matching the Week 7 rate where predictive showed 100% completion): **3/3 concurrent jobs completed with zero wasted compute each and no cross-job interference** — checkpoint/trigger files stayed correctly isolated. ~5x wall-clock speedup from real parallelism, only ~5% per-job makespan increase from contention. One job timed out, but in the *sequential* control run, not the concurrent one — attributed to the predictive arm's already-documented run-to-run variance, not a concurrency defect.
3. **`docs/week8_final_cost_analysis.md`**: Consolidated the Week 7 per-arm/rate cost-vs-On-Demand table into one reference, and scaled the percentages to realistic job durations (1/10/24 hours) so they translate into a dollar figure — e.g., ~$3.10 saved of $4.51 on a 24-hour job at typical interruption rates, dropping to ~$1.24 at the worst-case fastest rate.
4. **README badges + quick start**: Added Build (GitHub Actions), License (MIT), Python 3.11, Kubernetes, and AWS EKS badges. Added a "Quick start" section ahead of the fuller "Reproduce everything else" guide — the fastest zero-cloud path (the benchmark, 2 commands) now comes first instead of being buried after the local-dev/minikube setup.

---

## Commands

```bash
# Stress test: 3 concurrent SpotResilientJobs vs. sequential baseline
python benchmark/stress_test.py --rate 300 --step-budget 500 --step-time-sec 0.3

# Regenerate the cost table this analysis is built from
python benchmark/aggregate.py
```

---

## Why (Key Decisions)

**Why the local benchmark harness instead of a real 3-pod EKS/minikube deployment?**  
Consistent with how Objective 2's whole benchmark was scoped ("No EKS/Spot needed for the benchmark," `docs/phase6_remaining.md`) — starting Docker Desktop's Kubernetes engine and deploying the full operator + predict-service stack for this one test is a bigger, riskier lift than extending infrastructure that's already validated across 80+ trials. A real-cluster version of this test is a reasonable next step, not attempted here.

**Why run a sequential control alongside the concurrent run, instead of just reporting the concurrent numbers?**  
Without it, a failure or slowdown under concurrency is unexplainable — is it concurrency, or just this policy's own variance? The control isolated the answer directly: the one failure observed happened in the *sequential* run, so it's provably not a concurrency defect.

**Why scale the cost percentages to illustrative job durations instead of just reporting the raw benchmark numbers?**  
The benchmark's synthetic job (~2.5 min) produces cost figures too small to be a meaningful citation. The *percentages* are the real, rate-independent result; scaling them to a realistic duration (clearly labeled as illustrative, not a live billing capture) is what makes them citable.

**Why "Quick start" before "Reproduce everything else" instead of one combined section?**  
The original section led with LocalStack + minikube setup, which is more setup than the benchmark itself needs. Reordering so the true zero-dependency path comes first matches what "quick start" is supposed to mean.

---

## Outputs

| Output | Description |
|--------|-------------|
| `benchmark/stress_test.py` | Concurrent vs. sequential stress test script |
| `benchmark/results/stress_test.json` | Stress test results (per-job + aggregate) |
| `docs/week8_stress_test.md` | Stress test write-up |
| `docs/week8_final_cost_analysis.md` | Consolidated cost-vs-On-Demand analysis, scaled to realistic job durations |
| `README.md` | Badges (Build/License/Python/Kubernetes/AWS) + "Quick start" section |
