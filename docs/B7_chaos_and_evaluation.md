# Chaos Experiments, Benchmark Cost Analysis, Model Evaluation & Helm Finalization

**Phase:** Week 7 — Observability + CI/CD  
**Owner:** Person B (Helm/deployment README item is `[Both]`, this pass completed by Person B)  
**Status:** Complete — chaos experiment run against the real model, benchmark extended with real cost data, evaluation report written, Helm chart finalized with a working deployment guide.

---

## Objective

Run chaos experiments against the real Objective 3 model at various risk score levels, extend the benchmark harness to collect cost-vs-On-Demand data, produce a model evaluation report (PR curves, threshold analysis), and finalize the Argus Helm chart with a deployment README — Person B's three Week 7 deliverables plus the shared Helm item.

---

## What Was Done

1. **`chaos_threshold_sweep.py`**: Swept the shipped model's calibrated decision threshold across its actual observed score range on held-out data (not just the single best-F1 operating point). Found that the operator's configured `riskThreshold: 0.65` (`helm/argus/values.yaml`, `demo/spotresilientjob.yaml`) never fires against the real model — its max observed calibrated score is 0.00184, about 350x below that default.
2. **`plot_pr_curve.py`**: Generated a real PR curve figure (`docs/figures/pr_curve.png`) plus a threshold analysis table (precision/recall/alarm-volume tradeoff) from the shipped model on the same held-out test set reported in `docs/objective3_result.md`.
3. **`measure_lead_time.py` refactor**: Split the single-threshold lead-time script into a reusable `_load_test_predictions()` (model/data loading) and `lead_time_at_threshold()` (stats for one threshold), so the chaos sweep could reuse it instead of duplicating model-loading logic.
4. **`benchmark/aggregate.py` cost-vs-On-Demand extension**: Added a real dollar comparison against `c5.xlarge`'s actual eu-north-1 On-Demand rate ($0.188/hr — the same instance type Objective 1's real Spot node used). Found predictive's cost savings collapse to near-parity with no-protection (27.4% vs 25.6%) at the fastest interruption rate — checkpoint/migration overhead has a real dollar cost even when wasted compute is zero.
5. **`docs/week7_model_evaluation.md`**: Consolidated evaluation report tying the PR curve, threshold table, and chaos-sweep finding together, with an explicit recommendation for what `riskThreshold` should actually be set to.
6. **Fixed `riskThreshold` default (0.65 → 0.0015)** in `helm/argus/values.yaml` and the operator's Python fallback (`operator/controller/handlers.py`) — same finding as #1, fixed at the source. 0.0015 is the model's own best-F1 threshold.
7. **`helm/argus/README.md`**: full deployment guide — prerequisites, `helm upgrade --install`, deploying the predict-service and a training job, observability commands, teardown, and a table spelling out the `riskThreshold` gotcha (real model vs. mock predictor use two different score scales).
8. **`helm/argus/templates/NOTES.txt`**: printed automatically after `helm install`/`upgrade` — verification commands plus the same `riskThreshold` reminder, so it surfaces at the moment someone actually deploys, not just in a doc they may not read.
9. **`helm/argus/.helmignore`**: standard chart file, was missing.
10. **Left `demo/spotresilientjob.yaml`'s `riskThreshold: 0.65` unchanged**, documented instead — that manifest is shared with the mock-predictor demo (`demo/mock-predict.yaml`, `docs/A6_observability.md`'s dashboard screenshot), whose 0-1 output range genuinely needs 0.65. A single static default can't correctly serve both the mock and the real model.

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

# Install / upgrade the operator via Helm
helm upgrade --install argus ./helm/argus --namespace default

# Deploy the prediction service + a training job
kubectl apply -f k8s/predict-service.yaml
kubectl apply -f demo/spotresilientjob.yaml
```

---

## Why (Key Decisions)

**Why sweep thresholds instead of reporting one operating point?**  
"Chaos at various risk score levels" is the actual ask — a single best-F1 threshold hides how alarm volume and overhead trade off as the threshold moves. Sweeping it is also what surfaced that the real deployed default (`riskThreshold: 0.65`) was silently broken — invisible until measured, because the Week 7 dashboard demo used a mock predictor with a compatible 0-1 output range, not the real model.

**Why cost vs. On-Demand, not just wasted-compute seconds?**  
"Zero wasted compute" and "cheapest" are not the same claim. The roadmap asked for cost data explicitly, and computing it honestly surfaced a real, non-obvious finding rather than confirming the expected one — predictive's dollar advantage nearly disappears at high interruption rates because of its own checkpoint overhead, something the wasted-compute metric alone didn't show.

**Why refactor `measure_lead_time.py` instead of writing a separate sweep script from scratch?**  
The sweep and the single-threshold script need the exact same model/scaler/calibrator loading and the same per-group spike-row mapping. Duplicating that risks the two drifting out of sync silently; factoring it into `_load_test_predictions()` means there's one place that logic lives.

**Why not just fix `demo/spotresilientjob.yaml`'s threshold too, for consistency?**  
That file is genuinely used for two different scenarios: the mock-predictor demo (0-1 score ramp, 0.65 is correct) and real-model deployments (0.0001-0.002 range, 0.65 is broken). Changing its default would have silently broken the already-working, already-screenshotted dashboard demo. Documented the distinction inline instead of guessing which use case wins.

**Why fix the Python fallback (`RISK_THRESHOLD_DEFAULT`) if the CRD requires `riskThreshold` per job anyway?**  
The CRD schema makes the field required, so in normal operation the fallback is rarely reached. Fixed it anyway for defense-in-depth — a wrong hardcoded default is still a latent bug if the CRD requirement is ever relaxed or a job is created outside schema validation.

**Why a `NOTES.txt` and not just the README?**  
A README only helps if someone reads it before deploying. `NOTES.txt` prints automatically at the moment of `helm install`/`upgrade` — the reminder reaches the person actually about to hit this bug, not just the person browsing docs.

---

## Outputs

| Output | Description |
|--------|-------------|
| `docs/figures/pr_curve.png` | PR curve for the shipped model, held-out test set |
| `ml/model/chaos_threshold_sweep.json` | Per-threshold precision/recall/alarms/lead-time table (gitignored, local artifact) |
| `docs/week7_model_evaluation.md` | Consolidated evaluation report + `riskThreshold` recommendation |
| `docs/objective2_result.md` (Week 7 section) | Cost-vs-On-Demand findings |
| `benchmark/results/summary_table.csv` | Updated with `cost_on_demand_usd` / `cost_savings_vs_ondemand_pct` columns |
| `helm/argus/README.md` | Full deployment guide |
| `helm/argus/templates/NOTES.txt` | Post-install/upgrade reminder |
| `helm/argus/.helmignore` | Standard chart file, was missing |
| `helm/argus/values.yaml` | `riskThreshold` fixed: 0.65 → 0.0015 |
| `operator/controller/handlers.py` | Python-side fallback default fixed to match |
