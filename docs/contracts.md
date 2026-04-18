# Argus — Integration Contracts

Lock these with Person B **before either person writes application code**.
Any change to a contract requires both people to agree and update this doc.

---

## 1. FastAPI Prediction Endpoint

**Who owns it:** Person B  
**Who calls it:** Person A (the K8s operator)

```
GET /predict?instance_type={type}&az={az}

Response (200 OK):
{
  "instance_type": "m5.xlarge",
  "az":            "eu-north-1a",
  "risk_score":    0.82,           // float in [0.0, 1.0]
  "timestamp":     "2026-04-16T10:00:00Z"
}

GET /health → { "status": "ok" }
```

- Response time: < 200ms (operator polls every 60s)
- If the model is loading on startup, `/health` returns 503 until ready

---

## 2. SpotResilientJob CRD Fields

**Who defines the YAML schema:** Person A  
**Who reads it at runtime:** Person A (operator) + Person B (training job)

```yaml
apiVersion: argus.io/v1
kind: SpotResilientJob
metadata:
  name: <job-name>
spec:
  image: <docker-image>              # e.g. pytorch/pytorch:2.1
  command: [python, train.py]
  checkpointPath: s3://<bucket>/checkpoints/<job-name>   # no trailing slash
  checkpointIntervalSteps: 500       # training job saves every N steps
  riskThreshold: 0.65                # operator triggers above this score
  instanceFallback:                  # ordered list of fallback instance types
    - m5.large
    - c5.xlarge
status:
  lastRiskScore: 0.0                 # operator writes this each poll cycle
  lastCheckpointStep: 0
  phase: Pending | Running | Checkpointing | Migrating | Completed | Failed
```

---

## 3. S3 Checkpoint Path Format

```
s3://{checkpoint_bucket}/checkpoints/{job-name}/{step}/model.pt
s3://{checkpoint_bucket}/checkpoints/{job-name}/{step}/optimizer.pt
s3://{checkpoint_bucket}/checkpoints/{job-name}/latest   # plaintext file containing the latest step number
```

- `{checkpoint_bucket}` = value of Terraform output `checkpoint_bucket_name`
- Multipart upload used for files > 100 MB
- Person B's training job writes to this path; Person A's operator triggers the flush

---

## 4. SQS Message Schema

**Who publishes:** Person B (prediction service, optional) or Person A (operator internal)  
**Who consumes:** Person A (operator)

```json
{
  "job_name":           "cifar10-training",
  "risk_score":         0.87,
  "instance_type":      "m5.xlarge",
  "az":                 "eu-north-1a",
  "timestamp":          "2026-04-16T10:00:00Z",
  "recommended_action": "checkpoint_and_migrate"
}
```

`recommended_action` values: `checkpoint_and_migrate` | `checkpoint_only` | `monitor`

---

## 5. Docker Image Naming (ECR)

```
{account_id}.dkr.ecr.eu-north-1.amazonaws.com/argus/operator:{tag}
{account_id}.dkr.ecr.eu-north-1.amazonaws.com/argus/predict-service:{tag}
{account_id}.dkr.ecr.eu-north-1.amazonaws.com/argus/training-job:{tag}
```

Tag convention: `{git-sha-short}` for releases, `dev` for local testing  
Base images:
- operator: `python:3.11-slim`
- predict-service: `pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime`
- training-job: `pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime`

---

## 6. Environment Variables (shared reference)

| Variable | Used by | Value source |
|----------|---------|--------------|
| `CHECKPOINT_BUCKET` | operator, training job | Terraform output |
| `FEATURE_STORE_BUCKET` | Lambda, Person B pipeline | Terraform output |
| `RISK_EVENTS_QUEUE_URL` | operator | Terraform output |
| `PREDICT_SERVICE_URL` | operator | K8s Service ClusterIP |
| `RISK_THRESHOLD` | operator | SpotResilientJob spec (overrides default) |

---

*Last updated: 2026-04-18*  
*Agreed by: Person A — @Ganglet | Person B — @Rayyan-Mohammed*
