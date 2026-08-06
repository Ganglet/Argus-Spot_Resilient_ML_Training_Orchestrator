# Cost Back-of-Envelope for §1 (the "why it matters for expensive training" number)

Purpose: give the paper a *defensible* number for the motivation, without any
LLM experiment. All figures are **illustrative, published On-Demand list prices**
(us-east-1) — cite them as such and note they vary by region/time. The argument
is the *arithmetic and the ratio*, not price precision.

## Published anchor prices (AWS On-Demand list, us-east-1)

| Instance | GPUs | On-Demand \$/hr | Per-GPU \$/hr | Typical Spot \$/hr* |
|---|---|---:|---:|---:|
| `p4d.24xlarge` | 8× A100 40GB | 32.77 | 4.10 | ~11–16 |
| `p4de.24xlarge` | 8× A100 80GB | 40.97 | 5.12 | ~14–20 |
| `p5.48xlarge` | 8× H100 80GB | 98.32 | 12.29 | ~30–60 |

\* Spot is typically **60–70% off** On-Demand for these GPU types (more volatile
and less discounted than CPU Spot). Use ~65% off as the illustrative figure.

## The worked example to put in §1

Take a **16-node** A100 job on `p4d.24xlarge` (128 GPUs) — a modest large-model
training run — at an illustrative Spot rate of **~\$12/node-hr** (≈65% off
\$32.77), checkpointing **once per hour** (a common interval for large jobs).

**A single Spot reclaim mid-interval discards all uncheckpointed progress.**
Because the job is **synchronous data-parallel, one node's reclaim stalls all 16
nodes** — every node's work since the last checkpoint is lost:

```
discarded work per reclaim  =  16 nodes × up to 1 hr × $12/node-hr  ≈  $190
```

Plus the whole 128-GPU fleet sits idle during detect → reschedule → resume.

**Cost of a checkpoint, for contrast:** writing model + optimizer state to S3 is
a pause of seconds (state is tens of GB for a mid-size model; S3 ingest is fast),
i.e. **a few node-seconds of paused compute ≈ cents.**

```
ratio  =  ~$190 discarded  /  ~$0.10 checkpoint  ≈  3 orders of magnitude
```

Even the **single-node** version (8 A100s, 1 hr, \$12/node-hr) is **~\$12
discarded vs cents to checkpoint — still ~100×.**

**One-line for the paper:** *"A single Spot reclaim on a 16-node A100 job
checkpointing hourly discards on the order of \$190 of synchronous compute (and
idles 128 GPUs during recovery), against a checkpoint cost of cents — three
orders of magnitude. The mechanism we study exists to close that gap; we use
CIFAR-10 as a cheap, controlled testbed and the mechanism is workload-agnostic."*

## The frequency bridge (ties §1 to the §3.2 finding — use this too)

GPU Spot pools (`p4d`/`p5`) sit in AWS's **highest interruption-frequency
buckets** (often the >20% tier in the Spot Instance Advisor — the same data
`ml/data/pull_spot_advisor.py` pulls). And exposure **compounds with scale**: for
an *N*-node job where each node has per-interval reclaim probability *p*, the
chance **at least one** node is reclaimed is

```
P(≥1 reclaim)  =  1 − (1 − p)^N
```

which rises fast with *N* (e.g. p=0.05, N=16 → ~56% per interval). So a large
synchronous job effectively experiences interruptions **far more often than any
single node does** — pushing it into exactly the regime §3.2 identifies, where a
fixed 2-minute reactive notice stops providing useful lead time. **The stakes
(this section) and the finding (§3.2) point at the same place: big, expensive,
multi-node jobs.** That is the spine, not a sticker.

## Honesty notes
- These are list/illustrative prices — say so; don't present a single \$ as exact.
- Never imply we ran on A100/H100. CIFAR is the testbed; this section is
  *motivation*, and multi-node large-model validation is stated as future work.
