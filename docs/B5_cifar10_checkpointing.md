# CIFAR-10 Training Job & S3 Checkpointing

**Phase:** Week 5 — Operator Core & Checkpointing  
**Owner:** Person B  
**Status:** Complete — Training job dockerized, checkpoint logic integrated, operator flush trigger added.

---

## Objective

Build a standalone, interrupt-resilient training workload (CIFAR-10 image classification) that can save and resume state from S3. Implement the communication mechanism between the Kubernetes Operator (Person A's layer) and the training Pod (Person B's layer) to force an early checkpoint when spot risk is high.

---

## What Was Done

1. **`train.py` (PyTorch CNN)**: Built a PyTorch CIFAR-10 training script that actively loads from `s3://.../latest_checkpoint.pt` on spin-up and saves its state at the end of every epoch.
2. **Graceful `SIGTERM` Handling**: Registered a signal handler in the Python script. When Kubernetes evicts the Pod due to a Spot interruption, it sends a `SIGTERM`. The script intercepts this and flushes the current model state to S3 before exiting.
3. **Operator-to-Pod S3 Trigger**:
   - Added logic in `operator/controller/handlers.py` to drop a `_FLUSH_TRIGGER` marker file in the job's S3 folder when the predictive model flags high risk.
   - Added active micro-polling inside the inner training loop (every 100 batches) of `train.py` to check for this marker and flush the checkpoint early if it exists.
4. **Dockerization**: Packaged the script and `boto3` dependencies into a standalone Dockerfile inside `ml/cifar10_job/`.
5. **YAML Update**: Updated the demo `spotresilientjob.yaml` payload to use the newly created `cifar10-job:latest` container instead of the generic PyTorch image.

---

## Commands

```bash
# Build the local Docker image
docker build -t cifar10-job:latest ml/cifar10_job/

# Optional: Run locally without Docker
export S3_BUCKET=argus-checkpoints-844641713781
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
| `ml/cifar10_job/train.py` | PyTorch training logic with checkpoint resume and S3 polling. |
| `ml/cifar10_job/Dockerfile` | The container image definition for the job. |
| Operator Logic (`handlers.py`) | Added `trigger_s3_checkpoint()` for the Operator. |
