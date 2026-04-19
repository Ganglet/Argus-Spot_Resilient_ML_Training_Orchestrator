# EKS, IRSA, and ECR Setup

**Phase:** Week 3 — Kubernetes Auth & Container Registry  
**Owner:** Person A  
**Status:** Complete — EKS control plane live, IRSA verified, ECR repos ready, node group destroyed post-test

---

## Objective

Set up the Kubernetes cluster, give pods the ability to call AWS services without hardcoded credentials (IRSA), and create container registries for all three Argus images.

---

## 1. EKS Cluster (`argus-eks`)

**Kubernetes version:** 1.30  
**Region:** eu-north-1  
**Mode:** Public endpoint (operator kubectl access from laptop)

The cluster control plane is always running from Week 3 onward — it provides the OIDC issuer URL that IRSA depends on. Destroying it would invalidate the IRSA trust policy.

**Cost:** $0.10/hr ($72/month). Acceptable from Week 3 onward as it's needed permanently.

Node groups are separate from the control plane — they can be destroyed between sessions to save EC2 costs. Control plane continues billing regardless of whether any nodes exist.

**Note on instance type:** Initial deployment used `t3.medium` — failed in `eu-north-1` with `InvalidParameterCombination`. Switched to `t3.small`. For Week 6 production node groups, use `m5.large` or `c5.xlarge` Spot instances instead.

---

## 2. IRSA (IAM Roles for Service Accounts)

**Why IRSA:**  
Pods need to call S3 (checkpoint flush) and SQS (publish risk events). Static access keys inside pods are a security risk — if the image leaks, the keys leak. IRSA gives pods temporary, auto-rotating credentials tied to their Kubernetes identity.

**The trust chain:**

```
EKS OIDC Provider (registered with AWS IAM)
        ↓
IAM Role (argus-operator-irsa) — trust policy scoped to:
  - this specific OIDC provider
  - namespace: default
  - serviceaccount: argus-operator
        ↓
K8s ServiceAccount annotated with:
  eks.amazonaws.com/role-arn: arn:aws:iam::844641713781:role/argus-operator-irsa
        ↓
Pod uses that ServiceAccount → gets temporary AWS credentials via STS
```

**Resources created:**

| Resource | Purpose |
|----------|---------|
| `aws_iam_openid_connect_provider.eks` | Registers EKS cluster's OIDC endpoint with AWS IAM |
| `aws_iam_role.operator_irsa` | Role pods assume — trust policy scoped to specific ServiceAccount |
| `aws_iam_role_policy.operator_irsa` | Permissions: S3 checkpoint R/W, SQS send/receive/delete |

**IRSA Role ARN:** `arn:aws:iam::844641713781:role/argus-operator-irsa`

Use this ARN to annotate the K8s ServiceAccount in `operator/rbac.yaml` (Week 4):
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argus-operator
  namespace: default
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::844641713781:role/argus-operator-irsa"
```

---

## 3. Smoke Test

Deployed a pod with zero AWS credentials — only the `argus-operator` ServiceAccount:

```yaml
spec:
  serviceAccountName: argus-operator
  containers:
  - image: amazon/aws-cli:latest
    command: ["aws", "s3", "ls", "s3://argus-checkpoints-844641713781/"]
```

**Result:** Pod completed with no error, no output (bucket is empty — expected). The assumed role ARN in CloudTrail confirms IRSA worked:
```
arn:aws:sts::844641713781:assumed-role/argus-operator-irsa/...
```

The first test (`aws s3 ls` without a bucket) returned `AccessDenied` on `s3:ListAllMyBuckets` — correct, that permission is not in the policy. Only scoped bucket access is granted.

---

## 4. ECR Repositories

Three repositories created, each with a lifecycle policy keeping the last 5 images (auto-expires older ones):

| Repo | URL | Used for |
|------|-----|---------|
| `argus/operator` | `844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/operator` | kopf operator (Week 4) |
| `argus/predict-service` | `844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/predict-service` | FastAPI model (Week 4) |
| `argus/training-job` | `844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/training-job` | CIFAR-10 demo (Week 5) |

**Image tag convention:** `{git-sha-short}` for releases, `dev` for local testing.

**Push workflow (Week 4 onward):**
```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region eu-north-1 \
  | docker login --username AWS \
    --password-stdin 844641713781.dkr.ecr.eu-north-1.amazonaws.com

# Build and push
docker build -t argus/operator .
docker tag argus/operator:latest \
  844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/operator:dev
docker push 844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/operator:dev
```

---

## Cost Management

| Resource | Status after Week 3 | Cost |
|----------|---------------------|------|
| EKS control plane | Running | $0.10/hr ongoing |
| System node group (t3.small) | **Destroyed** | $0 |
| Spot node group | Never created (desired=0) | $0 |
| ECR repos | Running | ~$0 (< 500MB used) |

Node groups are destroyed after every test session. They are recreated in Week 6 when EKS is permanently needed.

**Destroy node group after any test:**
```bash
terraform destroy -target=aws_eks_node_group.system_nodes -auto-approve
```

---

## Key Decisions

**Why keep the EKS control plane running instead of destroying it?**  
The OIDC provider URL (`oidc.eks.eu-north-1.amazonaws.com/id/...`) is embedded in the IRSA trust policy. Destroying the cluster changes the URL, breaking IRSA. The ₹8/day cost is acceptable given EKS is needed permanently from Week 6 anyway.

**Why a separate `operator_irsa` role instead of updating the original `operator` role?**  
The original `argus-operator` role has an `ec2.amazonaws.com` trust policy (placeholder). IRSA requires an OIDC federated trust policy — these are structurally different. Creating a new role keeps the Terraform state clean and avoids a destructive update to the existing role.

**Why ECR lifecycle policy of 5 images?**  
Each Docker push creates a new image layer. Without a lifecycle policy, old images accumulate indefinitely. 5 images covers the last 5 deploys — sufficient for rollback without unbounded storage growth.
