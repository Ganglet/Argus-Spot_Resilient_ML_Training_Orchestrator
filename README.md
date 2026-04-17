# Argus — Spot-Resilient ML Training Orchestrator

A three-layer system that predicts EC2 Spot interruptions before they happen and automatically checkpoints + migrates running ML training jobs — zero human intervention.

```
EC2 Spot Price History
        │
        ▼
  Lambda (every 5 min)
        │  writes CSVs
        ▼
  S3 Feature Store ──► ML Model (Person B) ──► FastAPI /predict
                                                        │
                                          Kubernetes Operator (Person A)
                                                        │
                              ┌─────────────────────────┼──────────────────────┐
                              ▼                         ▼                      ▼
                    Flush Checkpoint to S3     Cordon Risky Node     Reschedule Pod
```

---

## Ownership

| Layer | Owner | Status |
|-------|-------|--------|
| AWS Infrastructure (Terraform) | Person A | ✅ Week 1 complete |
| Lambda price collector | Person A | ✅ Written, deploy in Week 2 |
| Kubernetes Operator (CRD + kopf) | Person A | Week 4–5 |
| ML Transformer model | Person B | Week 2–3 |
| FastAPI prediction service | Person B | Week 4 |
| End-to-end integration | Both | Week 5–6 |

---

## Repository Structure

```
argus/
├── terraform/                  # All AWS infrastructure — Person A owns this
│   ├── main.tf                 # Provider, billing alarm, VPC, subnets
│   ├── s3.tf                   # Checkpoint bucket + feature store bucket
│   ├── sqs.tf                  # Risk events queue + DLQ
│   ├── iam.tf                  # Lambda role + operator role (IRSA placeholder)
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
│
├── lambda/
│   └── price_collector/
│       ├── handler.py          # Pulls Spot price history → writes CSV to S3
│       └── requirements.txt
│
├── localstack/                 # Local AWS simulator — use this for all dev (free)
│   ├── docker-compose.yml
│   └── init/
│       └── 01_create_buckets.sh
│
├── operator/                   # Kubernetes Operator — Person A (Week 4–5)
├── ml/                         # ML model + FastAPI — Person B
├── helm/                       # Helm chart for EKS deployment (Week 6)
├── demo/                       # CIFAR-10 training job + SpotResilientJob manifest
├── monitoring/                 # Grafana dashboards
├── .github/workflows/          # CI/CD
└── docs/
    └── contracts.md            # ← READ THIS FIRST (Person B)
```

---

## For Person B — Read This First

Before writing any model or API code, read [docs/contracts.md](docs/contracts.md). It defines:

- The exact JSON shape your `/predict` endpoint must return
- Every field in the `SpotResilientJob` CRD
- The S3 checkpoint path format your training job writes to
- The SQS message schema
- ECR repo names and Docker image tags

**Nothing should be built until both people have agreed on these contracts.**

---

## What's Live in AWS (Week 1)

All resources are in `eu-north-1` (Stockholm). Provisioned via Terraform — do not create or modify these manually in the console.

| Resource | Name | Purpose |
|----------|------|---------|
| VPC | `argus-vpc` | Isolated network, 2 AZs |
| S3 | `argus-checkpoints-844641713781` | Model checkpoint storage (versioned) |
| S3 | `argus-feature-store-844641713781` | Spot price CSV pipeline output |
| SQS | `argus-risk-events` | Risk alert event bus |
| SQS | `argus-risk-events-dlq` | Dead-letter queue for failed messages |
| IAM Role | `argus-operator` | K8s operator AWS permissions (IRSA in Week 3) |
| IAM Role | `argus-lambda-price-collector` | Lambda AWS permissions |
| Budget | `argus-dev-budget` | $20/month alarm |

**Person B needs:**
- The feature store bucket name: `argus-feature-store-844641713781`
- The checkpoint bucket name: `argus-checkpoints-844641713781`

Your ML pipeline reads raw Spot price CSVs from:
```
s3://argus-feature-store-844641713781/raw/YYYY/MM/DD/HH/prices_*.csv
```

---

## Local Development Setup

Use LocalStack for all development. Do not touch real AWS until Week 6.

### Prerequisites

```bash
# Required
brew install awscli terraform docker
brew install --cask docker        # Docker Desktop

# Python (for Lambda + operator dev)
python3 -m venv .venv
source .venv/bin/activate
pip install boto3
```

### Start LocalStack

```bash
cd localstack/
docker compose up -d

# Verify — should show both argus buckets and both queues
aws --endpoint-url http://localhost:4566 s3 ls
aws --endpoint-url http://localhost:4566 sqs list-queues
```

### Point boto3 at LocalStack

In any script during local dev, add:
```python
import boto3

# Local dev
s3 = boto3.client("s3", endpoint_url="http://localhost:4566",
                  aws_access_key_id="test", aws_secret_access_key="test",
                  region_name="eu-north-1")

# Real AWS (Week 6+) — just remove endpoint_url
s3 = boto3.client("s3", region_name="eu-north-1")
```

---

## Terraform (Person A workflow)

```bash
cd terraform/

# First time only
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — add your email for billing alarm

terraform init
terraform plan    # preview changes
terraform apply   # create resources

# See all live resource IDs and names
terraform output
```

> **Never run `terraform apply` without reviewing `terraform plan` first.**
> EKS and NAT Gateway are intentionally excluded until Week 6 — adding them starts the billing clock.

---

## Integration Contracts (Summary)

Full details in [docs/contracts.md](docs/contracts.md).

**FastAPI endpoint (Person B builds, Person A calls):**
```
GET /predict?instance_type=m5.xlarge&az=eu-north-1a
→ { "instance_type": "m5.xlarge", "az": "eu-north-1a", "risk_score": 0.82, "timestamp": "..." }
```

**S3 checkpoint path (Person B writes, Person A triggers flush):**
```
s3://argus-checkpoints-844641713781/checkpoints/{job-name}/{step}/model.pt
```

**Custom Kubernetes resource (both use):**
```yaml
apiVersion: argus.io/v1
kind: SpotResilientJob
spec:
  image: pytorch/pytorch:2.1
  command: [python, train.py]
  checkpointPath: s3://argus-checkpoints-844641713781/checkpoints/my-job
  riskThreshold: 0.65
  instanceFallback: [m5.large, c5.xlarge]
```

---

## Cost Management

| Phase | Real AWS used | Expected cost |
|-------|--------------|---------------|
| Week 1–5 | S3 + SQS + IAM + Lambda | ~$0 (free tier) |
| Week 6–8 | + EKS + NAT Gateway | ~$5–15 total |

**Rules:**
- Use LocalStack for all dev until Week 6
- Run `terraform destroy -target=aws_eks_cluster.main -target=aws_nat_gateway.nat` after every EKS session
- EKS control plane costs $0.10/hr even with zero pods running
- A $20/month billing alarm is active — you'll get emailed at $16

---

## Week-by-Week Roadmap

| Week | Person A | Person B |
|------|----------|----------|
| 1 | ✅ Terraform base infra, VPC, S3, SQS, IAM | Pull Spot price history, EDA |
| 2 | EKS cluster, Lambda price collector live | Feature pipeline, PyTorch Dataset |
| 3 | IRSA, OIDC, ECR repos | Model training, MLflow, threshold tuning |
| 4 | CRD schema, kopf skeleton, Minikube | FastAPI /predict, Dockerfile, push to ECR |
| 5 | Operator core: cordon + reschedule | S3 checkpoint trigger, CIFAR-10 test job |
| 6 | EKS full deploy, Helm chart, SQS wiring | Chaos testing, benchmark collection |
| 7 | Prometheus + Grafana, GitHub Actions CI/CD | PR curves, evaluation report |
| 8 | ADRs, cost analysis, README polish | System paper, demo video |
