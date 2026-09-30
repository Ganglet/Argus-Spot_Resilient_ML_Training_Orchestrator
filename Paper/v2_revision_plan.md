# Argus — v2 Revision Plan (post-ML4Sys rejection)

_Owner split: **A = Angshuman** (systems, infra, benchmark harness, real-EKS, writing §1/§2/§3.1/§3.5/§5/abstract) · **B = Rayyan** (risk model, writing §3.2/§3.3/§3.4/§4)._

## Status

- **Rejected** from NeurIPS 2026 Workshop on ML for Systems. Avg rating 3.50 (haku 4/conf 4, ZNZL 3/conf 3), decision "No Recommendation".
- Non-archival venue, so the work is free to rework and resubmit anywhere.
- **arXiv v1 is up** (lightly cleaned: preprint mode, figures enlarged, §4 opener de-slopped). This doc is the plan for **arXiv v2** and an optional resubmission.

## One-line diagnosis

The systems half landed; the **ML half is what sank it at an ML venue**. Both reviewers converge on a single theme: **the predictor is never tested as a predictor, and the benchmark cannot test prediction** (Poisson kills have no learnable signal, and the "predictive" arm is a fixed lead parameter, not model output). Everything else is secondary to fixing that.

## What the reviews actually said

### Reviewer haku (rating 4, confidence 4) — the substantive one

Credited: the P(>=1)=1-(1-p)^N motivation, running the ML-free periodic baseline and reporting honestly that it wins, the clean operator/checkpoint separation.

Weaknesses:
1. **The predictor is never evaluated as a predictor** — no AUROC/AUPRC/precision-recall at the deployed 0.65 threshold, and it is trained on price-spike proxy, not real reclaims. When predictive loses, a reader can't tell if the model is bad or if prediction can't help.
2. **No non-learned predictive baseline** — AWS publishes per-pool interruption-frequency tiers (Spot Advisor, already cited); a threshold on those predicts without a model.
3. **The predictive arm is misconfigured** — 600 s lead at a 120 s interval causes constant migration (221.6 checkpoints, only 1 of 5 runs finishes). Comparing a badly-tuned arm to a well-tuned periodic arm doesn't answer the question.
4. **Single-run numbers** — because 4 of 5 predictive runs didn't finish, the wasted-compute/makespan for that arm come from one run. Table 1's 0.0 s wasted is not meaningful.
5. **Guideline may not hold at scale** — checkpoint is 3.8 MB here (near-zero write); at multi-node scale a checkpoint takes much longer, possibly longer than the useful lead, so "set lead just above write time" may break in the motivated setting.
6. **Motivation gap** — if a 2-minute notice exists, why not make checkpointing fast enough to fit inside it? The motivating example should say why prediction is preferable.
7. **Benchmark can't test prediction** — Poisson interruptions have no signal to learn, and the predictive arm's lead is a configured parameter, not model output. The benchmark can only compare lead-time settings, not predictors.
8. **AI-generated prose** — flagged §4's opener ("We consolidate the paper's disclosures here rather than let them scatter") and called the rest of that section slop.

### Reviewer ZNZL (rating 3, confidence 3)

Cons: narrow application field; single-node, small-model (CIFAR-10) demo; Figures 1 and 2 legibility.

## Strategic decision for v2 — pick the framing FIRST

The core critique (#7) forces a choice. Decide this before touching anything else.

- **Path A (recommended, ambitious): make the benchmark actually test prediction.** Replace Poisson kills with **real historical Spot price/interruption traces**, so the model's price-spike features genuinely correlate with kills, and run the **real model in the loop** (not a fixed lead). This directly answers #1, #3, #4, #7 at once and turns Argus into a genuine ML-for-systems paper. Public Spot data makes it feasible.
- **Path B (honest downscope): reframe as what it is** — a real-EKS survival demonstration + a lead-time sensitivity study + an honestly-characterized *advisory* model. Drop the "prediction beats checkpointing" central claim; lead with the guideline and the real-EKS result. Less work, weaker contribution, and it concedes the ML venue's main ask.

**Recommendation: Path A.** It is the only version that survives the same reviewers. Path B is the fallback if Path A's data work proves too heavy against MIRAGE/capstone priorities.

## v2 work items (owners + effort)

| # | Item (from review) | What to do | Owner | Effort |
|---|---|---|---|---|
| 1 | Benchmark can't test prediction (#7) | Replace Poisson with **real Spot-trace-driven kills**; run the **actual model in the loop**, not a fixed lead | **A** harness + **B** model | HIGH — the centerpiece |
| 2 | Predictor never evaluated (#1) | Put the model's **AUROC / AUPRC / precision-recall** into the paper at the best-F1 threshold; explain the 0.65 demo default never fires (max score ~0.0018) | **B** | LOW — data already in `docs/week7_model_evaluation.md` |
| 3 | No non-learned baseline (#2) | Add a **Spot-Advisor-tier threshold** arm to the harness | **A** arm + **B** tier logic | MED |
| 4 | Misconfigured arm / single-run 0.0 (#3,#4) | Re-run the 120 s condition with a **tuned lead** and enough budget so predictive **completes (1.0)**; kill the single-run headline | **A** | LOW-MED |
| 5 | Motivation gap (#6) | §1: state **why predict vs. just faster checkpointing** inside the 2-min notice | **A** | LOW (writing) |
| 6 | Guideline at scale (#5) | Measure **real checkpoint write time** at larger state, or caveat the guideline explicitly with that dependence | **A** measure + **B** write §3.3 | MED |
| 7 | §4 AI-slop (#8) | Rewrite §4 in plain human voice; no flourishes | **B** | LOW |
| 8 | Figure legibility (ZNZL) | Fig 1/2 enlarged (done for v1); keep large in v2 | **A** | DONE-ish |
| 9 | Narrow scope / single-node (ZNZL) | State honestly as scope; optionally one small **multi-node** run if infra allows | **A** | LOW to state, HIGH to run |

## Work split summary

**Angshuman (A):**
- Redesign the harness to replay real Spot traces (#1) and add the Spot-Advisor baseline arm (#3).
- Re-run the benchmark so the predictive arm completes; regenerate all tables/figures from the new runs (#4).
- Measure real checkpoint write time at larger state (#6).
- Rewrite §1 motivation (#5); keep figures legible (#8); own the scope statement (#9).
- Sections: §1, §2, §3.1, §3.5, §5, abstract.

**Rayyan (B):**
- Run the model **in the loop** on the trace-driven benchmark (#1).
- Produce and write up the **predictor-as-predictor evaluation** — AUROC/AUPRC/PR (#2).
- Define the Spot-Advisor tier-threshold logic (#3).
- Rewrite §4 in human voice (#7); write §3.3 scale caveat (#6).
- Sections: §3.2, §3.3, §3.4, §4.

## What we will NOT fix — state honestly in v2

- **Real reclaim labels remain blocked** (FIS on account subscription). The model is still trained on the price-spike proxy; a true reclaim-labeled evaluation stays future work. Say so plainly.
- **No large-model-scale validation.** CIFAR-10 stays the controlled testbed. State the mechanism is workload-agnostic; do not claim scale.

## Order of operations

1. **Decide Path A vs B** (both, together) — everything downstream depends on it.
2. In parallel: **B** does item 2 (cheap, data exists) while **A** does item 4 (rerun the fixed arm).
3. **A** builds the trace-driven harness + Spot-Advisor arm (items 1, 3); **B** plugs the model in.
4. Regenerate all tables/figures from the new runs.
5. Rewrite affected sections (§1, §3.2, §3.3, §3.4, §4).
6. **Joint human-voice pass over the whole paper** (see rules below).
7. Post **arXiv v2** with a one-line changelog; optionally resubmit to another workshop.

## Writing rules (carry into v2)

- **Human-voice pass over the WHOLE paper, both authors reading each other's sections** — a reviewer literally flagged AI phrasing, and it tarred the whole submission, not just §4.
- No em/en-dashes; no colons/semicolons as connective flourishes in prose.
- Every number verified against the source CSV, never from a prior draft (`docs/summary_table.csv`, `docs/week7_model_evaluation.md`).
- No fabricated headline numbers (the "12x recovery / 5.4 s" incident — recovery is not a clean win; do not reintroduce).

## Possible resubmission targets (after v2)

- Another systems-leaning ML workshop, or a student/industry track where a real-EKS demonstration + honest benchmark is valued.
- Only pursue if Path A lands; otherwise arXiv v2 is a fine terminal state for a portfolio artifact.
