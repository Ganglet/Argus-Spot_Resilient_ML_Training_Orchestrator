# Operator Core Logic & CIFAR-10 Checkpointing

**Phase:** Week 5 — Operator Core Logic [Both — first major integration]  
**Owner:** Person B (and Joint Tasks)  
**Status:** Complete — Full operator loop working on Minikube. Can submit a SpotResilientJob and see it survive a simulated interruption.

---

## Objective

Deliver the first major end-to-end integration: the Operator successfully polling the FastAPI prediction service and communicating an early checkpoint trigger via S3 to the running PyTorch (CIFAR-10) training Pod.

---

## What Was Done (Week 5 Integration)

1. **[Both] First integration session**: Deployed the FastAPI prediction service to Minikube, operator polls it.
2. **[B] Implement S3 checkpoint trigger in operator**: Added `trigger_s3_checkpoint()` into `operator/controller/handlers.py` to call `boto3` and write a `_FLUSH_TRIGGER` object indicating high spot eviction risk to flush the checkpoint.
3. **[B] Write test training job (CIFAR-10 in PyTorch)**: Built a training script (`train.py`) that checks for the S3 flush condition every 100 batches to support checkpoint resume, and dockerized it into `cifar10-job:latest`.
4. **[Both] End-to-end test on Minikube**: Submitted `SpotResilientJob` → simulated high risk → verified checkpoint + reschedule.
5. **[Both] Fix integration bugs**: Addressed environment discrepancies running LocalStack and Minikube. This week had the most debugging.

---

## Commands

```bash
# Build the local Docker image
docker build -t cifar10-job:latest ml/cifar10_job/

# Optional: Run locally without Docker
export S3_BUCKET=argus-checkpoints-844641713781
export AWS_ENDPOINT_URL=http://localhost:4566  # If testing with LocalStack
python ml/cifar10_job/train.py
```

---

## Why (Key Decisions)

**Why use S3 for Operator-to-Pod communication?**  
The Operator manages Kubernetes resources, while the Pod just runs a Python script. Instead of engineering a complex bidirectional GRPC or REST API directly into the training pod just to listen for flush requests, utilizing the S3 bucket as an intermediary queue (dropping a trigger file) is much more decoupled, fault-tolerant, and secure.

**Why implement both `SIGTERM` and S3 Polling?**  
The S3 micro-polling handles predictive, preemptive safety (orchestrated by the predictive ML component predicting an *upcoming* interruption). The `SIGTERM` handler is the last-resort fallback for when AWS issues a 2-minute interruption warning directly to the node, ensuring no data is lost even if the predictive model misses the risk.

---

## Outputs

| Output | Description |
|--------|-------------|
| Operator Logic (`handlers.py`) | Added `trigger_s3_checkpoint()` for the Operator. |
| `ml/cifar10_job/train.py` | PyTorch training logic with checkpoint resume and S3 polling. |
| `ml/cifar10_job/Dockerfile` | The container image definition for the CIFAR-10 job. |
