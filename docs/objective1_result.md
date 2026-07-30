# Objective 1 Result — Reactive Spot-Interruption Survival (2026-07-30)

Raw evidence for the paper figure. Captured on **real Spot nodes** in `eu-north-1`
(`c5.xlarge` / `m5.xlarge`, EKS 1.32). Reproduce with `scripts/objective1_real_spot.sh`.

## Method (honest framing)

The reactive interruption path was validated by running **AWS Node Termination
Handler (NTH) in Queue Processor mode** and injecting an event that conforms
exactly to AWS's `EC2 Spot Instance Interruption Warning` schema into NTH's SQS
queue. NTH cannot distinguish it from an EventBridge-delivered one and runs the
identical drain path. The instance is **not** AWS-reclaimed — this validates the
*handler*, not AWS's termination. A genuine AWS-issued reclaim (via FIS
`send-spot-instance-interruptions`) is deferred pending an account-plan fix (see
`problems_and_decisions.md` P-019).

Say in the paper: *"validated via schema-conformant injected Spot-interruption
events on live Spot instances; FIS-issued reclaim is future work."*

## Timeline

Training was live at **epoch 7** on Spot node `ip-10-0-2-196` (instance
`i-051ec341e23ec9e88`, AZ `eu-north-1b`) when the warning was injected.

| t (UTC)   | Event                                                        |
|-----------|--------------------------------------------------------------|
| 12:26:18  | NTH receives Spot Interruption Warning (SQS_MONITOR)         |
| 12:26:19  | Requesting drain → evicting `cifar10-test` (graceful SIGTERM)|
| 12:26:19  | SIGTERM handler writes checkpoint (epoch 8) to S3            |
| 12:26:25  | Node cordoned + drained — **10 s end-to-end**                |
| +~75 s    | Replacement pod on healthy node `ip-10-0-1-118` → resume     |

**Outcome:** interrupted at epoch 7-8 → resumed at **epoch 8** on a *different*
node. Only the in-progress epoch's work was lost.

## Raw log excerpts

### NTH (kube-system/aws-node-termination-handler) — the drain
```
12:26:18 INF Adding new event to the event store event={
  "Description":"Spot Interruption event received. Instance i-051ec341e23ec9e88 will be interrupted at 2026-07-30 12:26:15 +0000 UTC",
  "Kind":"SPOT_ITN","Monitor":"SQS_MONITOR","IsManaged":true,
  "NodeName":"ip-10-0-2-196.eu-north-1.compute.internal","ProviderID":"aws:///eu-north-1b/i-051ec341e23ec9e88"}
12:26:19 INF Requesting instance drain kind=SPOT_ITN node-name=ip-10-0-2-196...
12:26:19 INF Draining the node
12:26:19     evicting pod default/cifar10-test
12:26:19     evicting pod default/argus-operator-...
12:26:25 INF Node successfully cordoned and drained
           reason="Spot Interruption event received. Instance i-051ec341e23ec9e88 will be interrupted..."
```

### Node — cordoned
```
unschedulable=true   taints=node.kubernetes.io/unschedulable
```

### S3 — checkpoint written during the drain
```
latest_checkpoint.pt   3,951,157 bytes   (updated at drain time; SIGTERM save, epoch 8)
```

### Replacement pod (default/cifar10-test) — resumed on a healthy node
```
node = ip-10-0-1-118.eu-north-1.compute.internal   (cordoned ip-10-0-2-196 avoided)
Loading checkpoint from s3://argus-checkpoints-844641713781/checkpoints/cifar10-test/latest_checkpoint.pt
Resuming from epoch 8
```

## Contrast with Week 6

Week 6 used the operator's own `cordon + reschedule_pod(grace_period_seconds=0)`
— a SIGKILL, so no SIGTERM checkpoint (it relied on the pre-existing S3 marker).
Objective 1 exercises the **real NTH drain with a graceful SIGTERM checkpoint inside
the termination grace window** — a materially stronger, production-faithful claim.
