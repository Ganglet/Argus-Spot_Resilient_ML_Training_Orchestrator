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

---

### P-008 — Minikube binary: wrong architecture (darwin_amd64 on arm64)
**Week:** 4  
**Problem:** `brew install minikube` installed the amd64 binary. `minikube start` failed with `PROVIDER_DOCKER_INCORRECT_ARCH: Cannot use amd64 minikube binary to start minikube cluster with Docker driver on arm64 machine`.  
**Fix:** Downloaded native `darwin_arm64` binary directly from GitHub releases, installed to `/usr/local/bin/minikube`.  
**Lesson:** Same root cause as P-001 (Terraform). On Apple Silicon, always verify binaries are arm64 — Homebrew bottles sometimes lag behind or install Rosetta-compatible builds.

---

### P-009 — SQS publish hits real AWS instead of LocalStack
**Week:** 5  
**Problem:** `.env.local` sets `AWS_ENDPOINT_URL=http://localhost:4566` but `_boto3_client()` in `handlers.py` only reads `AWS_ENDPOINT_URL` via `os.environ.get("AWS_ENDPOINT_URL")`. The SQS queue URL in `.env.local` is `http://localhost:4566/000000000000/argus-risk-events` (LocalStack format), but boto3 resolved the endpoint to `https://sqs.eu-north-1.amazonaws.com` and threw `InvalidAddress`.  
**Fix (pending Week 6):** Pass `endpoint_url` explicitly in `_boto3_client()` when `AWS_ENDPOINT_URL` is set. Already done for S3 — apply same pattern to SQS.  
**Impact:** SQS publish is non-fatal (wrapped in try/except with WARNING log), so integration test still passed. Fix before Week 6.

---

### P-010 — Minikube loses loaded images on restart
**Week:** 5  
**Problem:** `minikube image load` loads an image into Minikube's internal Docker daemon. When Minikube is stopped and restarted, the image is gone — the internal daemon is reset. This caused repeated `ErrImageNeverPull` errors after every Minikube restart.  
**Fix:** Re-run `minikube image load argus/predict-service:latest` after every `minikube start`. For Week 6 this is moot — images come from ECR.  
**Lesson:** Minikube's image cache is ephemeral. For persistent local dev, use a local registry (`minikube addons enable registry`) or always script the image load as part of startup.

---

### P-011 — Person B's image on different machine — `minikube image load` doesn't transfer
**Week:** 5  
**Problem:** Assumed `minikube image load` on Person B's machine would make the image available on Person A's Minikube. They run on separate laptops — completely separate Docker daemons and Minikube clusters. The image never arrived.  
**Fix:** Person B exported with `docker save argus/predict-service:latest | gzip > predict-service.tar.gz`, transferred via WeTransfer, Person A loaded with `docker load` then `minikube image load`.  
**Lesson:** For cross-machine image sharing, always use `docker save/load`. From Week 6 onward this is solved by ECR — both developers push/pull from the same registry.

---

### P-012 — Minikube cached old image despite `minikube image load` with new tar
**Week:** 5  
**Problem:** After loading a new version of `argus/predict-service:latest`, the running pod continued using the old image. `docker inspect` showed different SHA256 digests between local Docker and Minikube's internal daemon. `minikube image load` silently skipped the update because the tag already existed.  
**Fix:** `kubectl delete deployment argus-predict-service` → `minikube ssh "docker rmi -f argus/predict-service:latest"` → `minikube image load argus/predict-service:latest` → `kubectl apply -f k8s/predict-service.yaml`.  
**Lesson:** `minikube image load` does not force-replace existing tags. To update an image, always force-remove it from Minikube's daemon first.

---

### ADR-005 — Workload node group is On-Demand `m7i-flex.large`, not Spot
**Decision:** The "spot" node group (`aws_eks_node_group.spot_nodes`) runs `capacity_type = ON_DEMAND` on a single Free-Tier-eligible type, `m7i-flex.large`.
**Why:** The AWS account is hard-restricted to Free-Tier-eligible instance types (see P-013). Real Spot never fulfilled, and non-free-tier types are rejected outright. `m7i-flex.large` (2 vCPU / 8 GB, x86) is the largest Free-Tier-eligible type in eu-north-1 and matches Person B's amd64 images.
**Impact:** The Week 6 interruption is *simulated* via the operator's cordon+delete rather than a real Spot reclaim. The migration mechanism is identical; only the trigger differs. Revert to `SPOT` + ML instance types once the account restriction is lifted or a different account is used. The resource is still named `spot_nodes` and keeps `lifecycle=spot` labels so manifests/selectors are unchanged.

---

### P-013 — AWS account is Free-Tier-restricted: only Free-Tier instance types will launch
**Week:** 6  
**Problem:** Every workload node group creation hung ~20 min in `CREATING` (no ASG, no health error) then failed `CREATE_FAILED`. Tried `g4dn.xlarge` (spot), `m5.xlarge`/`c5.xlarge` (spot and on-demand), `t3.xlarge` — all failed identically. The system node group (`t3.small`) always worked. Spot quota (32 vCPU) and on-demand quota (16 vCPU) were both fine; zero instances ever launched.  
**Root cause:** The final error surfaced it: `InvalidParameterCombination - The specified instance type is not eligible for Free Tier`. The account can only launch Free-Tier-eligible types. This is the same wall as P-006 (`t3.medium`), not understood as account-wide at the time.  
**Fix:** `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true` → allowed types in eu-north-1 are `t3.micro/small`, `t4g.micro/small` (ARM), `c7i-flex.large` (4 GB), `m7i-flex.large` (8 GB). Switched workload nodes to `m7i-flex.large` (x86, 8 GB) → launched in 1m41s.  
**Lesson:** On a restricted account, `describe-instance-types --filters Name=free-tier-eligible,Values=true` is the source of truth for what will launch. A node group stuck in `CREATING` with **no ASG and no health issue** is the signature of the launch being rejected before the ASG is even created. Do not use `t4g` (ARM) if the images are x86.

---

### P-014 — Operator image built for wrong architecture (arm64 on Apple Silicon → amd64 nodes)
**Week:** 6  
**Problem:** Operator pod crash-looped on EKS with `exec /usr/local/bin/python: exec format error`. The runbook `deploy` ran `docker build` on an Apple-Silicon Mac, producing an **arm64** image; the EKS nodes are **amd64**.  
**Fix:** `docker build --platform linux/amd64 …` (baked into `week6_runbook.sh`), pushed, `helm upgrade --set image.pullPolicy=Always` + rollout restart to force the node to re-pull. Person B's predict-service/training-job images were already amd64 (verified via `docker buildx imagetools inspect`).  
**Lesson:** Always `--platform linux/amd64` when building on Apple Silicon for x86 nodes. `:latest` + `IfNotPresent` will silently reuse a cached wrong-arch image — force `Always` (or a digest) after a rebuild.

---

### P-015 — Circular import crashed the operator (introduced by the P-009 fix)
**Week:** 6  
**Problem:** After the arch fix, the operator crashed with `ImportError: cannot import name '_boto3_client' from partially initialized module 'controller.handlers' (circular import)`. `handlers.py` imports `sqs_publisher` at module load; `sqs_publisher.py` imported `_boto3_client` from `handlers` at module load — a cycle. This was introduced by the P-009 fix (routing SQS through `handlers._boto3_client`) and never run on a live operator (Week 5 passed before it).  
**Fix:** Moved the `from controller.handlers import _boto3_client` in `sqs_publisher.py` from module level into `publish_risk_event()` (deferred import).  
**Lesson:** A "fix applied but never executed" is not a fix. Deferred (function-level) imports are the standard break for two modules that must reference each other.

---

### P-016 — predict-service Dockerfile path bug → `/health` 503 (Person B)
**Week:** 6  
**Problem:** predict-service pod ran but `/health` returned 503; logs showed `No such file or directory: /app/data/features.csv`. `ml/api/Dockerfile` copied the model + 95 MB features.csv to `/data/` and `/model/` (container root), but `app.py` reads `/app/data/` and `/app/model/`. The model-load fall-through to a nonexistent `argus-models` S3 bucket is what actually drove the 503.  
**Fix (Person B):** Corrected the Dockerfile COPY destinations, added `.dockerignore`, rebuilt and pushed. Person A fixed the stale Minikube manifest (`k8s/predict-service.yaml`): ECR image ref + `imagePullPolicy: Always`, and removed the dead `MODEL_PATH=/app/model.pt` (wrong path) and `MOCK_MODE` (removed from code in Week 6) env overrides so the verified baked-in defaults win.  
**Lesson:** Data + model are baked into the image by design (sub-2s pod ready). Test the *container's* absolute paths, not just local runs where CWD hides the mismatch.

---

### P-017 — predict-service 404 for `m5.large` — model has no features for that type/AZ
**Week:** 6  
**Problem:** With predict-service healthy, the operator got `404: No historical features found for this instance type & AZ` querying `instance_type=m5.large, az=eu-north-1a` (from `instanceFallback[0]`).  
**Fix:** Probed the endpoint — the model has real features for `m5.xlarge`, `m5.2xlarge`, `c5.xlarge`, `g4dn.xlarge` (all AZs), not `m5.large`. Changed `instanceFallback[0]` to `m5.xlarge` in `demo/spotresilientjob.yaml`.  
**Lesson:** The operator's `/predict` query is driven by `instanceFallback[0]` + a hardcoded `az=eu-north-1a`. That combo must exist in the training features or the risk poll 404s.

---

### P-018 — No training-pod manifest; operator only watches, doesn't create it
**Week:** 6  
**Problem:** The operator manages a pod named exactly `cifar10-test` (by CRD name) but never creates it — no Pod/Job manifest existed in the repo. Also each new training pod re-downloads CIFAR-10 (~170 MB) at startup, ~15–30 min on the slow source, with no node-local cache.  
**Fix:** Hand-wrote `demo/training-pod.yaml` — a bare Pod named `cifar10-test`, label `argus.io/job=cifar10-test`, ECR training image, `serviceAccountName: argus-operator` (reuses the operator's IRSA role for S3 checkpoint access), `nodeSelector: workload=ml-training`. Added `EPOCHS=30` + `PYTHONUNBUFFERED=1` for a long, observable run.  
**Lesson:** Bare Pod (not Deployment/Job) is required because the operator addresses the pod by exact name. Deleting it (reschedule) does not auto-recreate — resume is shown by re-applying the manifest, which loads the S3 checkpoint. For faster demos, cache the dataset on a node-local volume.

---

## Week 6 — Live Validation on Real EKS (PASSED, 2026-07-28)

First end-to-end run on **real EKS** (not Minikube). Full stack live: EKS cluster + `m7i-flex.large` nodes, operator (amd64) via Helm, real predict-service (real model + features), real training pod — all using **IRSA (zero static credentials)**, verified: `sts get-caller-identity` → `assumed-role/argus-operator-irsa/...` for both operator and training pod.

**Migration event** (forced by lowering `riskThreshold` 0.65→0.01 since the real model returned 0.0419) — one reconcile, all steps on real AWS:

| Step | Evidence | Δt |
|------|----------|----|
| Risk detected > threshold | operator log, real model score `0.0419` | — |
| Checkpoint flush | `_FLUSH_TRIGGER` written to real S3 | +0 ms |
| Risk event published | real SQS message (payload below) | +48 ms |
| Node cordoned | `ip-10-0-1-14` → `unschedulable=true` | +84 ms |
| Pod deleted | `cifar10-test` removed | +112 ms |
| Rescheduled to healthy node | recreated pod placed on `ip-10-0-2-220` (cordoned node avoided) | — |

Detection → full migration: **~112 ms**. SQS payload:
```json
{"job_name": "cifar10-test", "risk_score": 0.0419, "instance_type": "m5.xlarge",
 "az": "eu-north-1a", "timestamp": "2026-07-28T17:55:47Z", "recommended_action": "checkpoint_and_migrate"}
```
Resume-from-checkpoint validated: real `latest_checkpoint.pt` written to S3 by training via IRSA; `train.py load_checkpoint()` resumes at epoch+1 (confirmed earlier tonight and by Person B locally).

**Cost note:** EKS torn down to $0 after the run (`terraform destroy` of node groups + control plane; S3/SQS/Lambda/IAM retained).

**Open for the paper (NeurIPS ML4Sys 2026 poster):** the model returned a flat `0.0419` for every instance type/AZ — prediction discrimination is unproven and must be validated (AUC / lead-time / vs a reactive baseline) before the "predictive" claim holds. The systems layer is validated; the ML claim is not yet.

---

## Objective 1 — Real Spot Reclaim (in progress, 2026-07-29/30)

Goal: earn the "survived a real Spot reclaim" claim (vs the Week 6 *simulated* cordon). See `phase6_remaining.md` Objective 1 and `scripts/objective1_real_spot.sh`.

**ADR-006 — Account upgraded Free → Paid plan to unlock Spot.** The Free account plan (P-013) blocks all non-free-tier types. Upgraded to Paid (Billing console). Verified with a zero-cost `aws ec2 run-instances --dry-run --instance-type m5.large` → `DryRunOperation: would have succeeded`. Real Spot then launched: 2× `c5.xlarge` Spot nodes up in 2m45s (the exact type that failed all of Week 6). **Tradeoff:** the Free-Tier guardrail is gone — real charges are now possible, so `scripts/verify_teardown.sh` after every session + the $20 budget alarm matter more.

**Objective 1 stack that worked:** real Spot node group (SPOT + m5.large/c5.xlarge/m5.xlarge via `-var`), operator + predict-service deployed, **AWS Node Termination Handler** installed (IMDS mode, drains node on the Spot notice), `terminationGracePeriodSeconds: 90` on the training pod so the SIGTERM checkpoint completes inside the 2-min notice.

### P-019 — FIS blocked: `SubscriptionRequiredException` right after the Paid-plan upgrade
**Week:** Objective 1  
**Problem:** `aws fis create-experiment-template` (and `list-experiment-templates`) failed with `SubscriptionRequiredException: The AWS Access Key Id needs a subscription for the service`. FIS is the *only* way to trigger a real Spot interruption on demand (no public EC2 API for it). EC2/Spot worked, but FIS was not yet active — the Free→Paid upgrade propagated to EC2 first, FIS lagging.  
**Fix (pending):** no workaround — wait for FIS to activate. Because the check needs no running resources, tear EKS down to `$0` and poll for free: `./scripts/objective1_real_spot.sh check-fis` (or `aws fis list-experiment-templates --region eu-north-1`). Re-run the Objective 1 sequence once it reports ACTIVE. The `argus-fis-spot` IAM role persists.  
**Lesson:** After a plan/subscription change, secondary services (FIS) activate later than core ones (EC2). Preflight FIS **before** spinning up billable infra — `objective1_real_spot.sh fis-setup` now checks this and fails fast. Also: never swallow an AWS CLI error behind an assumed "already exists" — the original script hid this behind a bogus message.
**Update (2026-07-30):** still blocked after 24h+. Root cause is deeper than propagation: the Billing console shows the account is **still on the Free account plan** (`portal.aws.amazon.com/billing/signup/incomplete`) even though a payment method is added and paid EC2/Spot launches. "Upgrade plan" / resubscribe just redirects to the console without completing. So FIS (gated behind the Paid plan) stays off. This needs AWS Support to force-complete the plan upgrade — it can't be clicked through. **FIS deferred; interruption validated via injection instead (ADR-007).**

---

### ADR-007 — Interruption validated by event injection into NTH (queue mode), FIS deferred
**Decision:** Since FIS is blocked (P-019), validate the reactive interruption path by running **AWS Node Termination Handler in Queue Processor mode** and **injecting a schema-correct `EC2 Spot Instance Interruption Warning`** into its SQS queue, instead of an AWS-issued reclaim.
**Why:** NTH cannot distinguish an injected event from an EventBridge-delivered one — it runs the identical drain→SIGTERM→checkpoint→reschedule→resume path. This validates the *handler* faithfully, on real Spot nodes, without depending on FIS. The EventBridge rule is also wired so genuine reclaims flow in.
**Impact:** Honest paper framing — claim "handler validated via schema-conformant injected events + real Spot operation," NOT "AWS reclaimed the instance." FIS (true on-demand reclaim) remains the future deterministic-trigger step, pending the account-plan fix. See `scripts/objective1_real_spot.sh` (`nth-queue`, `inject`).

---

### P-020 — NTH `NoCredentialProviders`: pods can't use the node role (IMDS hop limit)
**Week:** Objective 1
**Problem:** NTH queue-mode crash-looped: `Unable to get AWS credentials — NoCredentialProviders: no valid providers in chain`. It was relying on the node instance role, but EKS managed nodes cap the IMDS `httpPutResponseHopLimit`, so pods can't reach `169.254.169.254` for the node role.
**Fix:** Give NTH **IRSA** — a role `argus-nth-irsa` trust-scoped to `kube-system:aws-node-termination-handler` (SQS receive/delete + ec2/asg describe), annotate the SA, and **restart the pod** (the pod-identity webhook injects the token only at creation). Baked into `objective1_real_spot.sh nth-queue`.
**Lesson:** On EKS, give controller pods AWS access via IRSA, not the node role. And annotating a ServiceAccount does nothing until its pods are **recreated**.

---

### P-021 — NTH silently ignored the interruption (`checkTagBeforeDraining`)
**Week:** Objective 1
**Problem:** After creds were fixed, NTH **consumed** the injected SQS message (queue drained to 0) but took **no action** — no cordon, no drain, no log. Default `checkTagBeforeDraining: true` makes NTH only drain instances tagged `aws-node-termination-handler/managed`; the EKS nodes aren't tagged, so it skipped silently.
**Fix:** `--set checkTagBeforeDraining=false` (and the deprecated `checkASGTagBeforeDraining=false`) + restart. Baked into the script.
**Lesson:** "Message consumed, nothing happened" on NTH = the managed-tag gate. Disable it or tag the nodes.

---

### P-022 — CIFAR-10 re-download (~35 min/pod) killed iteration → cached in S3 + initContainer
**Week:** Objective 1
**Problem:** Every training pod re-downloaded CIFAR-10 (~170 MB) from `cs.toronto.edu` at ~3 MB/min (15-35 min), wasting the billed window and, on the first Objective 1 attempt, letting training *complete* before the inject could land.
**Fix:** Uploaded the verified tar once (offline, `$0`) to `s3://argus-checkpoints-.../datasets/cifar-10-python.tar.gz`, and added an **initContainer** (`public.ecr.aws/aws-cli`) to `training-pod.yaml` that pulls it into a shared `emptyDir` at `/app/data` (185 MiB/s in-region) — `train.py` finds the tar, skips the download. Training now starts in seconds.
**Lesson:** Never let a pod download a fixed dataset from a slow external host on a billed cluster. Cache it in-region (S3) once; pull via an initContainer. (Same fix Person B needs for the Objective 2 benchmark's N runs.)

---

## Objective 1 — CAPTURED on Real Spot (2026-07-30)

Reactive Spot-interruption survival validated end-to-end on **real Spot nodes** (`c5.xlarge`/`m5.xlarge`), via schema-conformant event injection into NTH (ADR-007). Training was live at **epoch 7** when the interruption fired:

| t (UTC) | Event | Evidence |
|---------|-------|----------|
| 12:26:18 | NTH receives `EC2 Spot Instance Interruption Warning` (SQS_MONITOR, Kind=SPOT_ITN, IsManaged) | NTH log |
| 12:26:19 | Requesting drain → **evicting pod `cifar10-test`** (graceful, SIGTERM) | NTH log |
| 12:26:19 | SIGTERM handler **writes checkpoint (epoch 8) to S3** | `latest_checkpoint.pt` updated |
| 12:26:25 | **Node cordoned + drained** — 10 s end-to-end | node `unschedulable=true` + taint |
| +~75 s | Replacement pod on **healthy node `ip-10-0-1-118`** (cordoned node avoided) → **`Resuming from epoch 8`** | pod log |

**Result:** interrupted at epoch 7-8, resumed at epoch 8 on a different node — only the in-progress epoch's work lost. Full production path (warning → drain → SIGTERM checkpoint → reschedule → resume) exercised. Torn down to `$0` after; dataset + `argus-fis-spot`/`argus-nth-irsa` roles persist for reruns.

**vs Week 6:** Week 6 used the operator's cordon with `grace_period_seconds=0` (SIGKILL, no SIGTERM checkpoint). Objective 1 exercises the *real* NTH drain with a graceful SIGTERM checkpoint — a materially stronger claim.

**Still open:** FIS-issued reclaim (a genuine AWS termination via IMDS) pending the account-plan fix (P-019). Injection stands on its own; FIS would add "AWS actually pulled the instance."

---

## Week 7 — Observability (Prometheus + Grafana), 2026-08-02

Metrics were emitted since Week 6 (`metrics.py` on `:8080`, recorded in the reconcile loop) but nothing collected or displayed them. Week 7 closes the loop and captures the dashboard figure for the poster. Full write-up in `docs/A6_observability.md`. Built + screenshotted on **minikube** (real operator, real S3/SQS) to stay `$0` — see ADR-008. Problems hit, in order:

### P-023 — Helm couldn't install over the 105-day-old operator objects
`helm upgrade --install argus` refused: the `argus-operator` ServiceAccount, ClusterRole, ClusterRoleBinding and the `spotresilientjobs.argus.io` CRD already existed from the Week 4-5 `operator/rbac.yaml` + `kubectl apply` and were **not Helm-owned** (`missing key app.kubernetes.io/managed-by`). Adopting them via labels/annotations got further but then hit a field-manager conflict on the ClusterRole's `.rules` (`conflict with "kubectl-client-side-apply"`).
**Fix:** `helm uninstall` + delete the four stale pre-Helm objects (no `SpotResilientJob` CRs existed → cascade-safe) + clean `helm install`. **Lesson:** objects created by raw `kubectl apply` in earlier weeks can't be cleanly adopted by Helm when their spec differs; delete-and-let-Helm-own is simpler than adoption when nothing depends on them.

### P-024 — CRD vanished mid-reset → `server could not find spotresilientjobs.argus.io`
During the P-023 churn the CRD got deleted, and the subsequent `helm install` did **not** recreate it — the chart's `templates/crd.yaml` no-op'd because the CRD still existed at install time, then a later delete removed it. A stuck 106-day-old `cifar10-test` CR also blocked things (kopf finalizer left it `Terminating`).
**Fix:** cleared the stuck CR by removing its finalizer (`kubectl patch ... -p '{"metadata":{"finalizers":[]}}'`), then applied the CRD directly (`kubectl apply -f operator/crd/spotresilientjob.yaml`). **Note:** Helm's CRD-in-templates handling is order-sensitive — for a fresh cluster, apply the CRD explicitly before relying on the chart.

### P-025 — minikube clock skew made the risk ramp start already maxed
After the host slept, minikube's clock jumped: pod ages read 6-7h though just created. The mock-predict ramp keys off `time.monotonic()` from process start, so it had already reached its 0.90 ceiling — the operator saw `risk=0.900` on the first poll and checkpointed instantly, giving a **flat** dashboard line with no visible climb across the threshold.
**Fix:** `kubectl rollout restart deployment/argus-mock-predict` to reset the ramp clock **immediately before** applying the CR, so the reconcile loop polls a fresh 0.15→0.90 climb. Discovered while doing this that the operator **re-checkpoints every cycle** ("migration complete → back to Running") rather than freezing after the first — good for the metric time series (continuous checkpoint bars).

### P-026 — operator needs AWS credentials on minikube (no IRSA off-EKS)
The Helm chart's ServiceAccount carries the `eks.amazonaws.com/role-arn` IRSA annotation, which is a no-op outside EKS — so on minikube the operator's `boto3` S3/SQS calls have no credentials.
**Fix (local demo only):** created an `aws-creds` Secret from the host's exported credentials and injected it with `kubectl set env deployment/argus-operator --from=secret/aws-creds`, applied **after** `helm install` so a later `helm upgrade` doesn't strip it. Kept the chart IRSA-clean (did **not** add static creds to the chart — they'd be wrong on EKS). Delete the secret at teardown.

### ADR-008 — Self-contained annotation-scrape observability, built on minikube for the figure
**Decision:** ship Prometheus + Grafana as plain manifests under `k8s/monitoring/` using **pod-annotation service discovery** (no `kube-prometheus-stack`, no ServiceMonitor CRD), with the datasource + dashboard **provisioned on startup**. Build and screenshot on **minikube** against the **real** operator writing to **real S3/SQS** (creds via P-026), not on EKS.
**Why:** one `kubectl apply` brings up the whole stack on a bare cluster (no operator-of-operators to install first) — enough for a single scrape target and a poster figure. minikube keeps the "always `$0`" invariant while producing the exact dashboard that would run on EKS. CI (`deploy.yml`) was also guarded so the Helm deploy step is skipped when the cluster is torn down (build+push still runs) — the workflow previously would have gone red on every push to `main`.
**Result:** dashboard **"Argus — Spot Resilience"** captured showing predicted risk climb → cross the 0.65 threshold → proactive-checkpoint bars firing at the crossing, with real `_FLUSH_TRIGGER` writes to S3 and risk events to SQS underneath.