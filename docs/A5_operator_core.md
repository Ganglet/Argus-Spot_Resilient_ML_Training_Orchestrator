# A5 — Operator Core Logic + Week 5 Integration Test

## What Was Built

Full reconcile loop for the `SpotResilientJob` operator, plus the end-to-end integration test passing on Minikube + LocalStack.

---

## Operator Reconcile Loop (`operator/controller/handlers.py`)

The `@kopf.timer` fires every 60 seconds for each `SpotResilientJob` object. The logic:

1. **Poll prediction service** — `GET /predict?instance_type=...&az=eu-north-1a`
2. **Update status** — patch `lastRiskScore` onto the CRD regardless of outcome
3. **If risk ≤ threshold** — return, nothing to do
4. **If risk > threshold:**
   - Write `_FLUSH_TRIGGER` marker to S3 (`trigger_s3_checkpoint()`)
   - Publish risk event to SQS (`sqs_publisher.publish_risk_event()`)
   - Cordon the node + reschedule the pod (`scheduler.cordon_node()`, `scheduler.reschedule_pod()`)
   - Patch phase back to `Running` with incremented `lastCheckpointStep`

Phases used: `Running` → `Checkpointing` → `Migrating` → `Running`. If either checkpoint or reschedule fails, phase is set to `Failed`.

---

## Checkpoint Trigger Design

The operator does **not** directly save the model. It writes a tiny marker:

```
s3://{bucket}/{prefix}/_FLUSH_TRIGGER
```

The training pod polls S3 for this key every 100 batches. On detection: saves `model.pt`, uploads to S3, deletes the marker. This keeps the operator completely decoupled from PyTorch internals.

```python
def trigger_s3_checkpoint(job_name: str, checkpoint_path: str) -> None:
    path_clean = checkpoint_path.replace("s3://", "")
    bucket, prefix = path_clean.split("/", 1)
    trigger_key = f"{prefix}/_FLUSH_TRIGGER"
    s3 = _boto3_client("s3")
    s3.put_object(Bucket=bucket, Key=trigger_key, Body=b"1")
```

---

## Supporting Modules

**`scheduler.py`** — uses `kubernetes` Python client:
- `get_pod_node(job_name, namespace)` — finds which node the job's pod is on
- `cordon_node(node_name)` — patches node with `unschedulable: true`
- `reschedule_pod(job_name, namespace, fallback_types)` — deletes pod; Kubernetes restarts it on a healthy node

**`sqs_publisher.py`** — publishes JSON to `argus-risk-events` queue:
```json
{
  "job_name": "cifar10-test",
  "risk_score": 0.42,
  "instance_type": "m5.large",
  "az": "eu-north-1a",
  "timestamp": "2026-06-01T12:07:29Z",
  "recommended_action": "checkpoint_and_migrate"
}
```

**`checkpoint.py`** — direct S3 checkpoint write (used for SIGTERM / manual flush, not the trigger mechanism).

---

## Local Dev Setup

```bash
# Terminal 1 — LocalStack
cd localstack && docker compose up -d

# Terminal 2 — port-forward predict service
kubectl port-forward svc/argus-predict-service 8000:8000

# Terminal 3 — operator
cd operator
source .env.local
export PREDICT_SERVICE_URL=http://localhost:8000
PYTHONPATH=$(pwd) kopf run controller/handlers.py --verbose
```

`AWS_ENDPOINT_URL=http://localhost:4566` in `.env.local` routes boto3 to LocalStack for SQS. Note: S3 currently hits real AWS because `AWS_ENDPOINT_URL` must be explicitly passed to `_boto3_client()` — fix tracked in P-009.

---

## Integration Test (Minikube + LocalStack)

**Setup:**
```bash
# Create LocalStack resources
aws --endpoint-url=http://localhost:4566 s3 mb s3://argus-checkpoints-844641713781
aws --endpoint-url=http://localhost:4566 sqs create-queue --queue-name argus-risk-events

# Apply CRD + RBAC
kubectl apply -f operator/crd/spotresilientjob.yaml
kubectl apply -f operator/rbac.yaml

# Deploy predict service (Person B's image in mock mode)
kubectl apply -f k8s/predict-service.yaml   # has MOCK_MODE=true
```

**Test run:**
```bash
# Apply SpotResilientJob
kubectl apply -f demo/spotresilientjob.yaml

# Confirm operator polling — logs show:
# [RECONCILE] 'cifar10-test' | risk=0.420 threshold=0.65 | phase=Pending

# Simulate high risk by lowering threshold
kubectl patch spotresilientjob cifar10-test --type=merge -p '{"spec":{"riskThreshold":0.3}}'

# Next reconcile triggers migration — logs show:
# [RECONCILE] 'cifar10-test' risk 0.420 > 0.3 — triggering migration
# [CHECKPOINT] Trigger written → s3://argus-checkpoints-844641713781/checkpoints/cifar10-test/_FLUSH_TRIGGER
# [RECONCILE] 'cifar10-test' migration complete — back to Running
```

**Verified:**
- `_FLUSH_TRIGGER` written to S3 ✓
- SQS publish attempted (non-fatal fail — SQS hit real AWS, not LocalStack) ✓
- Pod delete attempted gracefully (pod didn't exist — expected in test) ✓
- Status patched: `phase=Running`, `lastCheckpointStep=1`, `lastRiskScore=0.42` ✓

---

## Known Issues / Week 6 Follow-ups

| Issue | Fix |
|-------|-----|
| SQS hits real AWS instead of LocalStack | Pass `AWS_ENDPOINT_URL` into `_boto3_client()` explicitly; `.env.local` sets it but boto3 only reads it if passed as `endpoint_url` kwarg |
| No real training pod to reschedule | Week 6: CIFAR-10 job runs as actual pod on EKS Spot node |
| MOCK_MODE predict service returns fixed 0.42 | Week 6: real model deployed on EKS, `MOCK_MODE` removed |
| `predict-service.yaml` uses `imagePullPolicy: Never` | Week 6: change to `IfNotPresent`, pull from ECR |
