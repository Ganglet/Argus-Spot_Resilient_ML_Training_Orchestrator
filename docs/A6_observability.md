# Observability — Prometheus + Grafana

**Phase:** Week 7 — Observability, CI/CD, Helm
**Owner:** Person A
**Status:** Complete — metrics collected and visualized end-to-end; CI guarded; Helm chart completed.

---

## Objective

The operator already *emitted* Prometheus metrics (Week 6, `metrics.py`), but
nothing collected or displayed them. Phase 7 closes that loop: deploy a
Prometheus that scrapes the operator, a Grafana with the Argus dashboard
provisioned on startup, complete the Helm chart so the metrics endpoint is
actually reachable, and stop the CI/CD workflow from failing against a
torn-down cluster.

---

## What Was Done

1. **Operator metrics Service + scrape annotations (`helm/argus`)**
   - New `templates/service.yaml`: `argus-operator-metrics` exposes the `:8080`
     metrics port (was emitted but had no Service, so nothing could reach it).
   - `templates/deployment.yaml`: named `metrics` container port + pod
     annotations (`prometheus.io/scrape|port|path`) so service discovery finds it.
   - `values.yaml`: `metrics.port` (8080), passed as `METRICS_PORT` to the pod.

2. **Prometheus (`k8s/monitoring/prometheus.yaml`)**
   - Self-contained: ServiceAccount + ClusterRole/Binding (list pods) +
     scrape-config ConfigMap + Deployment + Service.
   - Pod-annotation service discovery — zero per-target config; picks up the
     operator (and any future annotated pod) automatically. 10s scrape interval
     so a risk spike → checkpoint is legible on the dashboard.

3. **Grafana (`k8s/monitoring/grafana.yaml`)**
   - Datasource + dashboard **provisioned on startup** (no manual clicking).
   - Dashboard **"Argus — Spot Resilience"**: risk-score timeline with the 0.65
     trigger threshold drawn in, checkpoints-per-minute bars beneath it, and
     stat tiles (total checkpoints, jobs completed, current max risk).
   - Anonymous admin so a demo/screenshot needs no login (local use only).

4. **Helper script (`scripts/monitoring.sh`)** — `up | open | status | down`.
   Cluster-agnostic: **runs on minikube (free) or EKS**. Use minikube for the
   poster screenshot — same dashboard, zero AWS cost.

5. **CI/CD guard (`.github/workflows/deploy.yml`)** — build + push to ECR still
   runs on every push to `main`; the Helm deploy steps are now gated on the EKS
   cluster actually existing (`aws eks describe-cluster`). Since the cluster is
   normally destroyed to \$0 between sessions, the previous workflow would have
   gone red on every push — now it skips the deploy with a notice instead.

---

## Why (Key Decisions)

**Why pod-annotation discovery instead of a ServiceMonitor / kube-prometheus-stack?**
No CRD dependency, no operator-of-operators to install first — one `kubectl apply`
brings up the whole stack on a bare minikube. For a single scrape target and a
poster demo, the full Prometheus Operator is overkill.

**Why build/screenshot on minikube, not EKS?**
The dashboard is identical either way, and the guardrail on this account is
effectively gone (see `problems_and_decisions.md`). Minikube keeps the "always
\$0" invariant while producing the exact same poster figure.

**Why guard CI instead of deleting the workflow?**
Building + pushing the image on every `main` push is still useful (catches
Dockerfile breakage). Only the deploy is cluster-dependent — so gate that, keep
the build.

---

## Run it

```bash
helm upgrade --install argus ./helm/argus --namespace default   # scrape target
./scripts/monitoring.sh up      # Prometheus + Grafana
./scripts/monitoring.sh open    # port-forward -> http://localhost:3000
./scripts/monitoring.sh down    # tear down
```

See `k8s/monitoring/README.md` for the metric reference and dashboard details.

---

## Outputs

| Output | Description |
|--------|-------------|
| `helm/argus/templates/service.yaml` | operator metrics Service (`:8080`) |
| `helm/argus/templates/deployment.yaml` | named metrics port + scrape annotations |
| `k8s/monitoring/prometheus.yaml` | Prometheus + RBAC + annotation-based scrape |
| `k8s/monitoring/grafana.yaml` | Grafana + provisioned datasource + Argus dashboard |
| `scripts/monitoring.sh` | up/open/status/down helper |
| `.github/workflows/deploy.yml` | build always; deploy gated on cluster existing |

## Screenshot captured (2026-08-02)

Ran the full stack on minikube against the **real** operator (real S3/SQS, creds
injected per P-026): risk climbs 0.15 → crosses the 0.65 threshold → proactive
checkpoint bars fire at the crossing, cumulative-checkpoints panel ramps. This is
the observability poster figure. See `docs/problems_and_decisions.md` → *Week 7*
(P-023..P-026, ADR-008) for the problems hit while producing it. Drop the PNG in
`docs/figures/` if tracking it in-repo.

## Remaining (Phase 8, not Phase 7)

- README architecture Mermaid diagram.
- The 4-page poster.
