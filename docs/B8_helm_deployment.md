# Helm Chart Finalization & Deployment Guide

**Phase:** Week 7 — Observability + CI/CD  
**Owner:** Both (this pass completed by Person B)  
**Status:** Complete — chart finalized, real-model `riskThreshold` bug fixed, deployment README written.

---

## Objective

Finalize the Argus Helm chart and write the deployment guide that didn't exist — the chart itself worked (already used to produce the Week 7 Grafana dashboard screenshot), but there was no `README.md`, no `NOTES.txt`, no `.helmignore`, and a default value that was silently wrong against the real model.

---

## What Was Done

1. **Fixed `riskThreshold` default (0.65 → 0.0015)** in `helm/argus/values.yaml` and the operator's Python fallback (`operator/controller/handlers.py`) — 0.65 never fires against the real model's calibrated output (max ~0.0018, see `B7_chaos_and_evaluation.md`). 0.0015 is the model's own best-F1 threshold.
2. **`helm/argus/README.md`**: full deployment guide — prerequisites, `helm upgrade --install`, deploying the predict-service and a training job, observability commands, teardown, and a table spelling out the `riskThreshold` gotcha (real model vs. mock predictor use two different score scales).
3. **`helm/argus/templates/NOTES.txt`**: printed automatically after `helm install`/`upgrade` — verification commands plus the same `riskThreshold` reminder, so it surfaces at the moment someone actually deploys, not just in a doc they may not read.
4. **`helm/argus/.helmignore`**: standard chart file, was missing.
5. **Left `demo/spotresilientjob.yaml`'s `riskThreshold: 0.65` unchanged**, documented instead — that manifest is shared with the mock-predictor demo (`demo/mock-predict.yaml`, `docs/A6_observability.md`'s dashboard screenshot), whose 0-1 output range genuinely needs 0.65. A single static default can't correctly serve both the mock and the real model.

---

## Commands

```bash
# Install / upgrade the operator
helm upgrade --install argus ./helm/argus --namespace default

# Deploy the prediction service (plain manifest, not part of the chart)
kubectl apply -f k8s/predict-service.yaml

# Deploy a training job
kubectl apply -f demo/spotresilientjob.yaml

# Observability
./scripts/monitoring.sh up
./scripts/monitoring.sh open
```

---

## Why (Key Decisions)

**Why not just fix `demo/spotresilientjob.yaml` too, for consistency?**  
That file is genuinely used for two different scenarios: the mock-predictor demo (0-1 score ramp, 0.65 is correct) and real-model deployments (0.0001-0.002 range, 0.65 is broken). Changing its default would have silently broken the already-working, already-screenshotted dashboard demo. Documented the distinction inline instead of guessing which use case wins.

**Why fix the Python fallback (`RISK_THRESHOLD_DEFAULT`) if the CRD requires `riskThreshold` per job anyway?**  
The CRD schema makes the field required, so in normal operation the fallback is rarely reached. Fixed it anyway for defense-in-depth — a wrong hardcoded default is still a latent bug if the CRD requirement is ever relaxed or a job is created outside schema validation.

**Why a `NOTES.txt` and not just the README?**  
A README only helps if someone reads it before deploying. `NOTES.txt` prints automatically at the moment of `helm install`/`upgrade` — the reminder reaches the person actually about to hit this bug, not just the person browsing docs.

---

## Outputs

| Output | Description |
|--------|-------------|
| `helm/argus/README.md` | Full deployment guide |
| `helm/argus/templates/NOTES.txt` | Post-install/upgrade reminder |
| `helm/argus/.helmignore` | Standard chart file, was missing |
| `helm/argus/values.yaml` | `riskThreshold` fixed: 0.65 → 0.0015 |
| `operator/controller/handlers.py` | Python-side fallback default fixed to match |
