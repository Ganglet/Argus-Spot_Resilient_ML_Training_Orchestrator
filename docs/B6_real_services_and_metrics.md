# Real Services & Operator Metrics

**Phase:** Week 6 — EKS Deployment + Real Spot Instances  
**Owner:** Person B  
**Status:** Complete — FastAPI uses real model, images configured for ECR, Operator metrics implemented.

---

## Objective

Transition the deep learning prediction service from a local mock into a production-ready container running the real Transformer model. Instrument the Kubernetes Operator with Prometheus metrics to visually track risk scores and job completion rates. Finally, deploy the resilient CIFAR-10 workload onto a live EKS Spot Node and prove the end-to-end architecture works during a real interruption.

---

## What Was Done

1. **FastAPI Real Model Integration (`MOCK_MODE` Removed)**: 
   - Stripped the `MOCK_MODE` environment variable out of `k8s/predict-service.yaml`. 
   - The FastAPI app in `ml/api/app.py` now loads the real PyTorch `spot_transformer.pt` model and processes streaming `features.csv` data to serve actual spot interruption risk scores instead of a static test value.
2. **Container Build & Push Automation**: 
   - Created cross-platform bash & batch scripts (e.g., `scripts/build_and_push_all.bat`) to automate the building of `argus/predict-service` and `argus/training-job` Docker images and authenticating/pushing them to AWS ECR.
3. **Operator Prometheus Metrics (`metrics.py`)**: 
   - Initialized a Prometheus HTTP metrics server running on port 8080 inside the Operator (`main.py`).
   - Defined three key metrics in `operator/controller/metrics.py`:
     - `argus_checkpoints_total` (Counter): Tracking successful `_FLUSH_TRIGGER` writes to S3.
     - `argus_risk_score` (Gauge): A time-series gauge that reflects the risk score at every polling interval.
     - `argus_jobs_completed_total` (Counter): Evaluates if K8s ultimately flagged the Pod as `Succeeded`.
   - Instrumented the Operator's `reconcile` loop in `handlers.py` to seamlessly record these values without blocking K8s operations.
4. **EKS Job Deployment**: 
   - Loaded the `SpotResilientJob` CRD and applied `demo/spotresilientjob.yaml` targeting the newly built ECR image to start the PyTorch CIFAR-10 training on the real Spot node instances.

---

## Commands

```bash
# 1. Build and push image releases to ECR (requires Docker & AWS CLI)
.\scripts\build_and_push_all.bat latest

# 2. Deploy real Prediction Service to EKS
kubectl apply -f k8s/predict-service.yaml

# 3. Apply Custom Resource Definition for operator
kubectl apply -f operator/crd/spotresilientjob.yaml

# 4. Deploy the live Resilient Training Job
kubectl apply -f demo/spotresilientjob.yaml
```

---

## Why (Key Decisions)

**Why add Prometheus at the Operator layer?**  
The operator sits at the exact intersection between the ML predictions and the compute infrastructure. By tracking the `risk_score` alongside `checkpoint_count`, you can build Grafana dashboards displaying exactly when the Transformer model confidence spiked, followed immediately by the operator forcing the `_FLUSH_TRIGGER` before the inevitable AWS Spot termination notice. It verifies the predictive model's true accuracy against real infrastructure.

**Why remove MOCK_MODE entirely?**  
Week 5 intentionally decoupled the actual prediction inference to focus cleanly on testing the operator's checkpoint/reschedule logic locally heavily using a static `0.42` risk. Week 6 represents the "bridge" where the ML engineering meets the Ops engineering—letting the actual PyTorch inference output drive real cordon/reschedule commands on EKS.

---

## Outputs

| Output | Description |
|--------|-------------|
| `k8s/predict-service.yaml` | Production config with MOCK_MODE removed. |
| `scripts/push_*.bat` | Automated AWS ECR container image releases. |
| `operator/controller/metrics.py` | Prometheus tracking (Checkpoints, Risk, Jo |
| `operator/controller/handlers.py`| Updated to publish K8s reconcile steps to metrics. |