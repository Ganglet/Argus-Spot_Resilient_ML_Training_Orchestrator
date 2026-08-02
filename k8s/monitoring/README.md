# Argus Observability (Phase 7)

Prometheus + Grafana for the operator's metrics. The operator already emits
three metrics (`operator/controller/metrics.py`, served on `:8080`, recorded in
the reconcile loop); this stack **collects and visualizes** them.

| Metric | Type | Meaning |
|---|---|---|
| `argus_risk_score{job_name,instance_type,az}` | Gauge | model's predicted interruption risk, per poll |
| `argus_checkpoints_total{job_name}` | Counter | proactive checkpoints triggered (`_FLUSH_TRIGGER` writes) |
| `argus_jobs_completed_total{job_name}` | Counter | jobs K8s marked `Succeeded` |

## Run it (minikube — free, use this for the screenshot)

```bash
# operator must be running so there's a scrape target:
helm upgrade --install argus ./helm/argus --namespace default

./scripts/monitoring.sh up      # deploy Prometheus + Grafana
./scripts/monitoring.sh open    # port-forward 3000 (Grafana) + 9090 (Prometheus)
# -> http://localhost:3000  ->  Dashboards  ->  "Argus — Spot Resilience"
./scripts/monitoring.sh down    # tear the stack down
```

Grafana has anonymous admin enabled (no login) purely for the local demo — it is
**not** meant to be exposed publicly.

## How scraping works

No per-target config. Prometheus uses pod-annotation service discovery; the Helm
chart annotates the operator pod (`prometheus.io/scrape: "true"`,
`prometheus.io/port: "8080"`, `prometheus.io/path: "/metrics"`) and a
`argus-operator-metrics` Service exposes the port. Any pod carrying those
annotations is picked up automatically. Confirm the target is `UP` at
`http://localhost:9090/targets`.

## The dashboard

- **Predicted Interruption Risk** — `argus_risk_score` over time, with the 0.65
  trigger threshold drawn in. This is the poster figure: risk climbs, crosses
  the line, a checkpoint fires.
- **Checkpoints Triggered (per-minute)** — `increase(argus_checkpoints_total[1m])`
  as bars; each bar should line up with a risk spike above.
- **Total Checkpoints / Jobs Completed / Current Max Risk** — stat tiles.

To force a visible risk spike for the screenshot, lower `operator.riskThreshold`
or point the predict-service at data that scores high (see the operator's poll
loop in `operator/controller/handlers.py`).
