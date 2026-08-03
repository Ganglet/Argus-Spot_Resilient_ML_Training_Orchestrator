# Argus — 4-page Poster Blueprint (NeurIPS ML4Sys 2026, OpenReview)

**Framing: SYSTEMS-LED.** Lead with the real-EKS interruption survival + the
benchmark; the prediction model is an honest *secondary/advisory* result. This
blueprint is "cover in this order" — write prose from it, don't paste it. Every
number below is sourced from `docs/objective{1,2,3}_result.md` and
`problems_and_decisions.md`. Voice: neutral academic ("we" — two authors);
double-check the venue's anonymization rule before submitting.

Target layout: **4 pages** body + refs. Figures: **Fig 1** architecture (README
mermaid, re-rendered clean), **Fig 2** Grafana risk→checkpoint (Phase 7 shot),
**Fig 3** wasted-compute-by-arm (`benchmark/results/figures/`), **Table 1** Obj1
timeline, **Table 2** benchmark sweep.

---

## Title + Abstract (~120 words)

**Title options:** "Argus: Predictive Checkpointing for Spot-Interrupted ML
Training" / "Surviving Spot Reclaims: A Kubernetes Operator for Resilient ML
Training."

**Abstract — cover in this order:**
1. Spot instances are ~70–90% cheaper but reclaimed on 2 minutes' notice; long ML
   training jobs lose work on every interruption.
2. Argus = a 3-layer system (Transformer risk predictor → kopf Kubernetes operator
   → checkpoint/resume training job) that migrates jobs *before* reclaim.
3. **Headline result:** validated end-to-end on **real EKS** — a real Spot node
   drained on a genuine 2-minute warning, the job checkpointed via SIGTERM and
   **resumed from epoch 8 on a healthy node**, only the in-progress epoch lost.
4. A controlled benchmark (80 trials) quantifies *when* prediction earns its
   complexity: predictive checkpointing eliminates wasted compute, and reactive
   checkpointing collapses toward no-protection once interruptions come faster
   than the fixed 2-minute notice window.
5. One honest sentence on scope: the predictor is an advisory signal (14.7×
   base-rate lift on a proxy label); real-interruption ground truth is future work.

---

## §1 Introduction / Motivation (~0.5 page)

**Cover in this order:**
1. The cost gap (Spot vs On-Demand) and why it's tempting for ML training.
2. The catch: 2-minute reclaim notice; naive jobs restart from scratch → wasted
   GPU-hours, non-deterministic makespan.
3. The reviewer's implicit question, stated up front so you own it: *"AWS already
   gives a free 2-minute notice — why predict at all?"* Promise to answer it
   quantitatively in §3.2.
4. Contributions (bulleted):
   - A working, **real-EKS-validated** operator that survives a real Spot drain
     with graceful SIGTERM checkpointing (§3.1).
   - A controlled benchmark isolating *when* predictive beats reactive/periodic
     checkpointing (§3.2).
   - An honest characterization of the risk predictor and its ceiling (§3.3).
   - Full observability + reproducible artifacts (§3.4).

---

## §2 System Design (~1 page, with Fig 1)

**Cover in this order:**
1. **Fig 1 (architecture).** Three layers + the two interruption paths converging
   on one SIGTERM→checkpoint→reschedule→resume flow.
2. **Layer 1 — prediction:** Lambda pulls Spot price history every 5 min → S3
   feature store → Transformer (`SpotInterruptionPredictor`, 13 features, seq_len
   24) → FastAPI `/predict` returns a risk score.
3. **Layer 2 — orchestration:** kopf operator, `SpotResilientJob` CRD; reconcile
   loop polls `/predict`; on risk > threshold (0.65) it writes a `_FLUSH_TRIGGER`
   to S3, cordons the node, reschedules the pod, publishes an SQS risk event.
   Decoupled checkpoint design (operator signals; training pod owns the flush).
4. **Layer 3 — training:** CIFAR-10 job polls the trigger every 100 batches, saves
   `model.pt`; a SIGTERM handler checkpoints on drain; resumes from the last epoch.
5. **Two paths, one mechanism:** *predictive* (operator pre-migrates) and
   *reactive* (real AWS 2-min warning via the Node Termination Handler) both land
   on the same checkpoint/resume path. This is the key design point.
6. One paragraph on infra choices (brief, cite ADRs): EKS+IRSA (zero static
   creds), Terraform, kopf-over-controller-runtime (single Python stack).

---

## §3 Evaluation (~1.75 pages)

### §3.1 Real-EKS interruption survival — the systems result (Table 1)

**Cover in this order:**
1. Setup: real EKS, **real Spot nodes** (`c5.xlarge`/`m5.xlarge`), IRSA, NTH in
   queue mode. Training live at epoch 7.
2. **Table 1 — timeline** (from `objective1_result.md`):
   warning → NTH drain (10 s) → SIGTERM checkpoint (epoch 8 → S3) → replacement
   pod on healthy node (~75 s) → **"Resuming from epoch 8."**
3. Result sentence: interrupted at epoch 7–8, resumed at epoch 8 on a different
   node; only the in-progress epoch's work lost.
4. **HONEST DISCLOSURE #1 (do not bury):** the interruption was delivered by
   **injecting a schema-conformant `EC2 Spot Instance Interruption Warning`** into
   NTH's queue, *not* an AWS-issued FIS reclaim. NTH cannot distinguish the two, so
   the drain→checkpoint→resume path is genuinely exercised; a *forced* AWS reclaim
   (FIS `send-spot-instance-interruptions`) is future work, blocked on an account
   subscription issue, not the design. (cite ADR-007, P-019.)
5. Contrast with Week-6 cordon (SIGKILL, grace=0): Objective 1 exercises the real
   NTH drain + graceful SIGTERM — a materially stronger claim.

### §3.2 Benchmark: when does prediction pay? (Table 2, Fig 3)

**Cover in this order:**
1. Method: 4 arms (no-protection, periodic, reactive-on-notice, predictive) share
   one job; harness kills on a **Poisson** schedule at 4 rates (MTBF 120/300/600/
   1800 s); **5 reps each = 80/80 trials.** Controlled injection, not real Spot
   (that's §3.1). Note the harness respawn-race bug you found and fixed *before*
   trusting numbers (24 respawns/1 checkpoint → 24/24 after fix) — signals rigor.
2. **Table 2 — wasted compute (s), makespan, recovery, checkpoints** per arm×rate.
   Headline numbers at MTBF=120 s: no-protection **202.3**, reactive **169.4**,
   periodic **4.3**, predictive **0.0 ± 0.0**.
3. **The "why predict?" answer (this is the paper's argument):** reactive's 120 s
   notice ≈ the 120 s mean interval, so it rarely gets enough lead to checkpoint →
   its wasted compute (169 s) collapses toward no-protection's (202 s).
   **Reactive's fixed 2-min notice stops helping exactly when interruptions come
   faster than once per ~2 min** — a realistic aggressive-Spot regime.
4. **HONEST DISCLOSURE #2:** predictive's `0.0` rides on `risk_lead_seconds=300`,
   a **benchmark assumption, not a measured property of the trained model** (§3.3
   shows the proxy label can't measure real lead time). State plainly: "this shows
   what a predictive system achieves *given* ~5 min reliable lead; it does not
   prove the current model delivers that lead." Don't conflate.
5. **HONEST DISCLOSURE #3:** periodic (no ML) nearly matches predictive on wasted
   compute at high rate and **wins makespan (159 s vs 270 s) + cost** (predictive
   over-checkpoints, 35.6 vs 24). So predictive's *clean* wins are two: **zero
   wasted compute** and **recovery latency 5.4 s vs periodic's 65.7 s (~12×)** —
   lead with those, credit periodic openly. **Fig 3** = wasted-compute-by-arm.

### §3.3 The risk predictor — honest secondary result

**Cover in this order:**
1. What it is: Transformer on live `eu-north-1` Spot price history; a proxy label
   (`is_spike = price > prev×1.01`), 0.078% positive — very rare.
2. Bugs fixed to make it real (one line each): train/serve scaler skew (the
   flat-0.0419 cause), 3-epoch smoke-train, train/val leakage from overlapping
   windows, FocalLoss `alpha` no-op, uncalibrated output.
3. **Result: 14.68× base-rate lift, 5-seed mean, 95% CI ≈ [9.9×, 19.5×]** — cite
   the mean, not the lucky shipped checkpoint (0.048/21.8×). 5/5 seeds landed
   9.5–22.6×, none collapsed → a real if weak, repeatable signal.
4. **HONEST DISCLOSURE #4:** this is lift **on the proxy task**, not real reclaim
   prediction. Two negative results reported (cross-AZ feature, the real
   Spot-Advisor interruption-rate feature — a static per-type rate, no time
   signal). **Ceiling = label quality**; real interruption ground truth is blocked
   (no historical store exists; needs forward capture or FIS). Present as
   **advisory**, never "predicts real interruptions."

### §3.4 Observability (~2 sentences + Fig 2)

Operator emits Prometheus metrics (`argus_risk_score`, `argus_checkpoints_total`,
`argus_jobs_completed_total`); Grafana dashboard shows risk crossing the 0.65
threshold and the proactive checkpoint firing at that instant. **Fig 2** =
the live dashboard (real operator, real S3/SQS, on minikube).

---

## §4 Limitations (~0.25 page — consolidate the disclosures)

One tight paragraph re-stating: (a) Obj1 = injected (not FIS-issued) reclaim;
(b) predictive's lead time is a benchmark parameter, not a model property;
(c) periodic is a strong ML-free baseline — prediction's edge is recovery latency,
not raw waste; (d) proxy label caps the predictor; (e) synthetic training job in
the benchmark (mechanics, not SOTA accuracy). Owning these *is* the credibility.

## §5 Related Work + Conclusion + Future Work (~0.5 page)

- **Related (brief):** Spot-resilience checkpointing systems; ML-for-systems
  interruption prediction; K8s operators for stateful workloads. 4–6 refs.
- **Conclusion:** Argus works end-to-end on real infra; the benchmark maps the
  regime where prediction beats the free reactive notice.
- **Future work:** FIS-forced real reclaims once the account clears; forward
  interruption-label capture (EventBridge→S3) to replace the proxy; measure the
  model's real lead time to close the §3.2 assumption.

---

## Pre-submission checklist
- [ ] All four honest disclosures present and *not* buried.
- [ ] "Why predict?" answered quantitatively (§3.2), not hand-waved.
- [ ] Predictive numbers labeled as lead-time-assumption, not model-measured.
- [ ] 14.7× always tagged "proxy label."
- [ ] Obj1 always "injected schema-conformant event," never "AWS reclaimed it."
- [ ] Figures legible at poster/print size; Fig 2 trimmed to the clean climb.
- [ ] Anonymization matches the venue rule.
