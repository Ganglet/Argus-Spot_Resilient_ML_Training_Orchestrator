# Problems & Decisions Log

Running log of every non-trivial problem encountered and every key architectural decision made. Updated as the project progresses.

---

## Architecture Decisions

### ADR-001 — NAT Gateway deferred to Week 6
**Decision:** Remove NAT Gateway from Week 1 Terraform. Add it only in `eks.tf` when EKS nodes need outbound internet.  
**Why:** NAT Gateway costs $0.045/hr ($32/month) just for existing. Private subnet nodes don't need internet until Week 6 when EKS is permanently live. Lambda runs outside the VPC so it doesn't need NAT.  
**Impact:** Private subnets have no outbound route until Week 6. Acceptable — nothing runs in private subnets before then.

---

### ADR-002 — EKS deferred to Week 6 (control plane exception)
**Decision:** `eks.tf` code written in Week 2 but node groups not deployed until Week 6. Control plane kept live from Week 3 onward for IRSA.  
**Why:** EKS control plane + node group = ~$110/month if left running. Node groups are the expensive part (EC2 instances). The control plane alone ($72/month) is unavoidable from Week 3 because its OIDC URL is needed for IRSA.  
**Impact:** All Kubernetes development in Weeks 4–5 happens on Minikube locally. Migration to real EKS in Week 6.

---

### ADR-003 — Separate IRSA role instead of updating existing operator role
**Decision:** Created `argus-operator-irsa` as a new IAM role rather than updating `argus-operator`.  
**Why:** The original role has an `ec2.amazonaws.com` trust policy. IRSA requires an OIDC federated trust policy — fundamentally different structure. Updating in-place would cause a destructive Terraform replacement. New role keeps state clean.  
**Impact:** Week 4 operator ServiceAccount must annotate with `argus-operator-irsa` ARN, not `argus-operator` ARN.

---

### ADR-004 — Lambda runs outside VPC
**Decision:** Price collector Lambda is not placed inside the VPC.  
**Why:** Placing Lambda in a VPC requires a NAT Gateway for it to reach the EC2 pricing API (an internet endpoint). NAT costs $32/month. Lambda outside VPC has free internet access by default.  
**Impact:** Lambda cannot reach VPC-internal resources (e.g. RDS). Not needed for this function — it only calls EC2 APIs and writes to S3 (both internet-reachable).

---

## Problems Encountered

### P-001 — Terraform provider binary: wrong architecture (darwin_amd64 on arm64)
**Week:** 1  
**Problem:** `terraform plan` timed out with "failed to instantiate provider." Terraform installed via Homebrew was the x86_64 binary running under Rosetta on Apple Silicon. It downloaded the `darwin_amd64` AWS provider, which timed out under Rosetta.  
**Fix:** Downloaded native `darwin_arm64` Terraform binary directly from HashiCorp releases. Re-ran `terraform init` to download the correct provider.  
**Lesson:** Always verify `file $(which terraform)` shows `arm64` on Apple Silicon before running init.

---

### P-002 — Lambda env var name mismatch
**Week:** 2  
**Problem:** `lambda.tf` (written by Person B) passed `BUCKET_NAME` as the environment variable. `handler.py` reads `os.environ["FEATURE_STORE_BUCKET"]`. This would cause a `KeyError` crash on every Lambda invocation.  
**Fix:** Updated `lambda.tf` to pass `FEATURE_STORE_BUCKET`.  
**Lesson:** Integration contracts must specify not just the API shape but also env var names. Added to `docs/contracts.md`.

---

### P-003 — `AWS_REGION` is a reserved Lambda env var
**Week:** 2  
**Problem:** `lambda.tf` also set `AWS_REGION` as an environment variable. AWS throws `InvalidParameterCombination` on deploy — this variable is reserved and set automatically by Lambda.  
**Fix:** Removed `AWS_REGION` from the env vars block. `handler.py` already falls back to `os.environ.get("AWS_REGION", "eu-north-1")` which reads the auto-set value correctly.

---

### P-004 — `.gitignore` corrupted to UTF-16 encoding
**Week:** 2  
**Problem:** Person B's `.gitignore` was saved in UTF-16 encoding (wide characters: `# T e r r a f o r m`). Git treated the file as binary. Rules were not applied, causing `features.csv`, `raw_spot_prices.csv`, and `spot_transformer.pt` (5.5MB) to be committed.  
**Fix:** Rewrote `.gitignore` in UTF-8. Ran `git rm --cached` on all committed binary/data files.  
**Lesson:** Never copy-paste `.gitignore` content from editors that default to UTF-16 (e.g. Notepad on Windows). Always verify with `file .gitignore`.

---

### P-005 — EKS credentials expired mid-apply
**Week:** 3  
**Problem:** During `terraform apply` for the EKS cluster, the AWS root access key was deactivated mid-operation (security incident — key was accidentally shared in chat). Terraform failed with `UnrecognizedClientException`. The cluster was created in AWS but marked as "tainted" in Terraform state.  
**Fix:** Created a new access key, reconfigured AWS CLI, ran `terraform untaint aws_eks_cluster.main`, reapplied.  
**Lesson:** Never share access keys in any medium — chat, email, screenshots. Always use IAM users with scoped permissions rather than root credentials.

---

### P-006 — `t3.medium` not launchable in account
**Week:** 3  
**Problem:** EKS node group with `t3.medium` failed: `InvalidParameterCombination - The specified instance type is not eligible for Free Tier`.  
**Fix:** Changed instance type to `t3.small`. Node group deployed successfully.  
**Note:** For Week 6 production Spot node group, use `m5.large`, `c5.xlarge`, or `g4dn.xlarge` — these are the instance types the operator's fallback list covers and are available in `eu-north-1` for Spot.

---

### P-007 — Binary and data files committed to git
**Week:** 2  
**Problem:** Person B committed `spot_transformer.pt` (5.5MB), `raw_spot_prices.csv`, `features.csv`, and EDA PNG files before `.gitignore` rules were enforced. These bloat git history permanently — even after deletion, the blobs remain in `.git/objects`.  
**Fix:** `git rm --cached` removed them from tracking. `.gitignore` updated to cover `ml/data/*.csv`, `ml/data/*.png`, `*.pt`.  
**Lesson:** Run `git status` and review every file before `git add`. Never use `git add -A` without checking output first. The git history still contains these blobs — to fully purge, `git filter-branch` or `git filter-repo` would be needed (not worth it at this stage).
