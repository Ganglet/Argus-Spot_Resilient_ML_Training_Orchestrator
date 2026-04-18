# Infrastructure — VPC, S3, SQS, IAM

**Phase:** Week 1 — Foundation  
**Owner:** Person A  
**Status:** Complete — all resources live in AWS (`eu-north-1`)

---

## Objective

Provision the base AWS infrastructure that every other Argus component depends on — network, storage, messaging, and IAM permissions — before any application code is written.

---

## 1. Networking (VPC)

Created an isolated VPC (`10.0.0.0/16`) with 2 availability zones to satisfy EKS's multi-AZ requirement.

```
VPC: 10.0.0.0/16
├── Public subnets:  10.0.1.0/24 (eu-north-1a), 10.0.2.0/24 (eu-north-1b)
└── Private subnets: 10.0.10.0/24 (eu-north-1a), 10.0.11.0/24 (eu-north-1b)
```

Public subnets host load balancers. Private subnets host EKS nodes (Week 6). An Internet Gateway serves public subnets. NAT Gateway is intentionally absent until Week 6 — it costs $0.045/hr just for existing.

Subnets carry `kubernetes.io/role/*` tags required for EKS to auto-discover them for load balancer placement.

---

## 2. Storage (S3)

Two buckets, both encrypted (AES256) and fully public-access blocked:

**`argus-checkpoints-844641713781`**  
Versioned. Stores model state every N training steps. Versioning ensures a corrupt checkpoint doesn't overwrite a good one — the operator can roll back.

**`argus-feature-store-844641713781`**  
Stores Spot price CSVs written by the Lambda every 5 minutes. Lifecycle rule expires `raw/` prefix after 180 days — 6 months of history is sufficient for model training.

Bucket names are suffixed with the account ID (`844641713781`) to guarantee global uniqueness without guessing.

---

## 3. Messaging (SQS)

**`argus-risk-events`** — main event queue. FastAPI prediction service publishes here when risk score crosses threshold. The operator subscribes and triggers checkpoint + migration.

Key settings:
- `visibility_timeout = 120s` — if the operator crashes mid-processing, the message reappears after 2 min for retry
- `receive_wait_time = 20s` — long polling, reduces empty-receive API calls (cheaper)

**`argus-risk-events-dlq`** — dead-letter queue. Messages that fail 3 consecutive processing attempts land here for inspection. Retention: 14 days.

---

## 4. IAM

**`argus-lambda-price-collector`** — Lambda execution role. Permissions: `ec2:DescribeSpotPriceHistory`, `s3:PutObject` on `raw/*` prefix of feature store, CloudWatch Logs. Scoped to minimum required.

**`argus-operator`** — Placeholder operator role. Permissions: S3 multipart upload to checkpoint bucket, SQS send/receive/delete on risk-events queue. Trust policy is `ec2.amazonaws.com` placeholder — replaced with OIDC trust in Week 3 (see `03_eks_irsa_ecr.md`).

---

## 5. Billing Alarm

AWS Budget `argus-dev-budget` — $20/month limit, email alert at 80% ($16). Created before any other resource.

---

## Terraform Commands

```bash
cd terraform/
cp terraform.tfvars.example terraform.tfvars   # fill in alert_email
terraform init
terraform plan
terraform apply
terraform output   # prints all resource IDs and names
```

---

## Outputs

| Output | Value |
|--------|-------|
| `checkpoint_bucket_name` | `argus-checkpoints-844641713781` |
| `feature_store_bucket_name` | `argus-feature-store-844641713781` |
| `risk_events_queue_url` | `https://sqs.eu-north-1.amazonaws.com/844641713781/argus-risk-events` |
| `vpc_id` | `vpc-0668f313571cb5cde` |
| `private_subnet_ids` | `subnet-0db7828c27e3323e5`, `subnet-0f61981aee08352e9` |
| `public_subnet_ids` | `subnet-0b58a4c76d4184fa0`, `subnet-0e92a02f84695480a` |

---

## Key Decisions

**Why eu-north-1?** Stockholm region — lowest latency from India for Spot price data collection. Also tends to have lower Spot prices than us-east-1.

**Why not use the default VPC?** Default VPC has no private subnets, no proper tagging, and is shared across all your AWS experiments. A dedicated VPC keeps Argus isolated.

**Why suffix bucket names with account ID?** S3 bucket names are globally unique across all AWS customers. Using a predictable name like `argus-checkpoints` would likely already be taken.
