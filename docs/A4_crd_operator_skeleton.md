# CRD + kopf Operator Skeleton

**Phase:** Week 4 — Kubernetes Operator Foundation  
**Owner:** Person A  
**Status:** Complete — CRD live on Minikube, operator running, handlers verified

---

## Objective

Define the `SpotResilientJob` custom Kubernetes resource and register kopf event handlers that react to its lifecycle. No AWS calls yet — Week 5 fills in the reconcile logic.

---

## 1. SpotResilientJob CRD

**File:** `operator/crd/spotresilientjob.yaml`  
**Registered as:** `spotresilientjobs.argus.io`  
**Short name:** `srj`

The CRD defines the schema for the custom resource both people interact with. Full OpenAPI v3 validation is enforced by the API server — malformed specs are rejected at apply time.

**Spec fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | string | ✅ | Docker image for the training job |
| `command` | string[] | ✅ | Command to run inside the container |
| `checkpointPath` | string (s3://…) | ✅ | S3 URI where training job saves checkpoints |
| `checkpointIntervalSteps` | integer | — | Steps between checkpoints (default: 500) |
| `riskThreshold` | float [0,1] | ✅ | Operator triggers above this score |
| `instanceFallback` | string[] | ✅ | Ordered fallback instance types |

**Status fields (operator writes):**

| Field | Type | Description |
|-------|------|-------------|
| `phase` | enum | `Pending` / `Running` / `Checkpointing` / `Migrating` / `Completed` / `Failed` |
| `lastRiskScore` | float | Most recent score from the prediction service |
| `lastCheckpointStep` | integer | Training step of the last checkpoint flush |

The `status` subresource is separate from `spec` — only the operator can write it (not kubectl apply from user manifests).

**`kubectl get srj` columns:**
```
NAME           PHASE     RISKSCORE   CHECKPOINTSTEP   AGE
cifar10-test   Pending   0           0                5m
```

---

## 2. RBAC

**File:** `operator/rbac.yaml`

Three resources created:

| Resource | Purpose |
|----------|---------|
| `ServiceAccount/argus-operator` | Identity the operator pod runs as. Annotated with IRSA role ARN for Week 6 EKS deploy. |
| `ClusterRole/argus-operator` | Permissions: manage `spotresilientjobs`, read/patch `nodes`, read/delete/create `pods`, write `events` + `configmaps` (kopf internal state) |
| `ClusterRoleBinding/argus-operator` | Binds the ClusterRole to the ServiceAccount |

---

## 3. kopf Operator

**Files:** `operator/controller/handlers.py`, `operator/controller/main.py`

Three handlers registered:

### `@kopf.on.create` — `on_create`
Fires when a `SpotResilientJob` is applied. Initialises status:
```
phase: Pending
lastRiskScore: 0.0
lastCheckpointStep: 0
```

### `@kopf.on.update` — `on_update`
Fires when the spec changes. Logs the diff. Week 5: handle `riskThreshold` changes mid-run.

### `@kopf.on.delete` — `on_delete`
Fires when the resource is deleted. Week 5: flush a final checkpoint before the pod is removed.

### `@kopf.timer` — `reconcile`
Fires every 60 seconds (configurable via `POLL_INTERVAL_SECONDS` env var). This is the main control loop.

**Current behaviour (Week 4):** logs that a poll cycle would happen.  
**Week 5 behaviour:** calls `GET /predict`, compares against `riskThreshold`, triggers checkpoint + cordon + reschedule if exceeded.

```python
# Week 5 reconcile loop (stub in handlers.py):
risk = httpx.get(f"{PREDICT_SERVICE_URL}/predict",
                 params={"instance_type": ..., "az": ...}).json()
if risk["risk_score"] > spec["riskThreshold"]:
    checkpoint.flush(name, spec["checkpointPath"])
    scheduler.cordon_node(node_name)
    scheduler.reschedule_pod(pod_spec, spec["instanceFallback"])
    sqs_publisher.publish(name, risk)
```

---

## 4. Smoke Test

Applied `demo/spotresilientjob.yaml` to Minikube:

```bash
kubectl apply -f demo/spotresilientjob.yaml
kubectl get spotresilientjobs
```

**Observed operator logs:**
```
[CREATE] SpotResilientJob 'cifar10-test' in namespace 'default'
  image:            pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime
  checkpointPath:   s3://argus-checkpoints-844641713781/checkpoints/cifar10-test
  riskThreshold:    0.65
  instanceFallback: ['m5.large', 'c5.xlarge']

[RECONCILE] 'cifar10-test' | phase=Pending | threshold=0.65 | predict_url=http://localhost:8000
```

Status patched to Kubernetes confirmed:
```yaml
status:
  phase: Pending
  lastRiskScore: 0.0
  lastCheckpointStep: 0
```

Reconcile timer fires every 60 seconds as expected.

---

## Local Dev Workflow

```bash
# Start Minikube (first time — CRD + RBAC already applied from Week 4)
minikube start --driver=docker --cpus=2 --memory=4096

# Install operator dependencies
cd operator/
pip install -r requirements.txt

# Run operator locally (watches Minikube)
kopf run controller/handlers.py --verbose

# In a separate terminal — submit a test job
kubectl apply -f demo/spotresilientjob.yaml
kubectl get spotresilientjobs

# Clean up
minikube stop
```

---

## Key Decisions

**Why kopf over writing a controller from scratch?**  
kopf handles all the Kubernetes watch loop boilerplate — retries, finalizers, status patching, timer management. Writing this from scratch in the `kubernetes` Python client would be ~500 lines of plumbing before any business logic. kopf reduces that to decorated functions.

**Why a timer-based reconcile instead of pure event-driven?**  
Risk scores change continuously even if the `SpotResilientJob` spec doesn't change. A timer ensures the operator polls the prediction service on a fixed cadence regardless of whether a Kubernetes event fired. The 60-second interval matches the operator's SLA from `docs/contracts.md`.

**Why `clusterwide=True` in `main.py`?**  
Training jobs can run in any namespace. Scoping to `default` would break multi-namespace deployments in Week 6+.
