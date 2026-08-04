# Chaos Experiments, Benchmark Cost Analysis & Model Evaluation

**Phase:** Week 7 — Observability + CI/CD  
**Owner:** Person B  
**Status:** Complete — chaos experiment run against the real model, benchmark extended with real cost data, evaluation report written.

---

## Objective

Run chaos experiments against the real Objective 3 model at various risk score levels, extend the benchmark harness to collect cost-vs-On-Demand data, and produce a model evaluation report (PR curves, threshold analysis) — Person B's three Week 7 deliverables.

---

## What Was Done

1. **`chaos_threshold_sweep.py`**: Swept the shipped model's calibrated decision threshold across its actual observed score range on held-out data (not just the single best-F1 operating point). Found that the operator's configured `riskThreshold: 0.65` (`helm/argus/values.yaml`, `demo/spotresilientjob.yaml`) never fires against the real model — its max observed calibrated score is 0.00184, about 350x below that default.
2. **`plot_pr_curve.py`**: Generated a real PR curve figure (`docs/figures/pr_curve.png`) plus a threshold analysis table (precision/recall/alarm-volume tradeoff) from the shipped model on the same held-out test set reported in `docs/objective3_result.md`.
3. **`measure_lead_time.py` refactor**: Split the single-threshold lead-time script into a reusable `_load_test_predictions()` (model/data loading) and `lead_time_at_threshold()` (stats for one threshold), so the chaos sweep could reuse it instead of duplicating model-loading logic.
4. **`benchmark/aggregate.py` cost-vs-On-Demand extension**: Added a real dollar comparison against `c5.xlarge`'s actual eu-north-1 On-Demand rate ($0.188/hr — the same instance type Objective 1's real Spot node used). Found predictive's cost savings collapse to near-parity with no-protection (27.4% vs 25.6%) at the fastest interruption rate — checkpoint/migration overhead has a real dollar cost even when wasted compute is zero.
5. **`docs/week7_model_evaluation.md`**: Consolidated evaluation report tying the PR curve, threshold table, and chaos-sweep finding together, with an explicit recommendation for what `riskThreshold` should actually be set to.

---

## Commands

```bash
# PR curve + threshold analysis
python ml/model/plot_pr_curve.py

# Chaos experiment: sweep risk thresholds, show alarm/recall/overhead tradeoff
python ml/model/chaos_threshold_sweep.py

# Single-threshold lead time (used internally by the sweep too)
python ml/model/measure_lead_time.py

# Re-aggregate the benchmark with cost-vs-On-Demand included
python benchmark/aggregate.py
```

---

## Why (Key Decisions)

**Why sweep thresholds instead of reporting one operating point?**  
"Chaos at various risk score levels" is the actual ask — a single best-F1 threshold hides how alarm volume and overhead trade off as the threshold moves. Sweeping it is also what surfaced that the real deployed default (`riskThreshold: 0.65`) was silently broken — invisible until measured, because the Week 7 dashboard demo used a mock predictor with a compatible 0-1 output range, not the real model.

**Why cost vs. On-Demand, not just wasted-compute seconds?**  
"Zero wasted compute" and "cheapest" are not the same claim. The roadmap asked for cost data explicitly, and computing it honestly surfaced a real, non-obvious finding rather than confirming the expected one — predictive's dollar advantage nearly disappears at high interruption rates because of its own checkpoint overhead, something the wasted-compute metric alone didn't show.

**Why refactor `measure_lead_time.py` instead of writing a separate sweep script from scratch?**  
The sweep and the single-threshold script need the exact same model/scaler/calibrator loading and the same per-group spike-row mapping. Duplicating that risks the two drifting out of sync silently; factoring it into `_load_test_predictions()` means there's one place that logic lives.

---

## Outputs

| Output | Description |
|--------|-------------|
| `docs/figures/pr_curve.png` | PR curve for the shipped model, held-out test set |
| `ml/model/chaos_threshold_sweep.json` | Per-threshold precision/recall/alarms/lead-time table (gitignored, local artifact) |
| `docs/week7_model_evaluation.md` | Consolidated evaluation report + `riskThreshold` recommendation |
| `docs/objective2_result.md` (Week 7 section) | Cost-vs-On-Demand findings |
| `benchmark/results/summary_table.csv` | Updated with `cost_on_demand_usd` / `cost_savings_vs_ondemand_pct` columns |
