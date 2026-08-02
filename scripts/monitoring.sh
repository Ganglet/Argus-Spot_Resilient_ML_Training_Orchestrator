#!/usr/bin/env bash
#
# Argus observability stack (Prometheus + Grafana) — Phase 7.
# Cluster-agnostic: works on minikube (free, use this for the dashboard
# screenshot) or the real EKS cluster. Scrapes the operator's metrics via
# pod annotations, no per-target config.
#
# Usage:
#   ./scripts/monitoring.sh up        # deploy Prometheus + Grafana into ns monitoring
#   ./scripts/monitoring.sh open      # port-forward Grafana (3000) + Prometheus (9090)
#   ./scripts/monitoring.sh status    # pods + whether the operator target is being scraped
#   ./scripts/monitoring.sh down      # delete the monitoring namespace (frees everything)
#
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MON="$HERE/k8s/monitoring"

case "${1:-}" in
  up)
    kubectl apply -f "$MON"
    echo "waiting for Prometheus + Grafana to be ready..."
    kubectl -n monitoring rollout status deploy/prometheus --timeout=120s
    kubectl -n monitoring rollout status deploy/grafana --timeout=120s
    echo "✅ up.  Next:  ./scripts/monitoring.sh open"
    ;;
  open)
    echo "Grafana   -> http://localhost:3000  (Dashboards -> 'Argus — Spot Resilience')"
    echo "Prometheus-> http://localhost:9090"
    echo "Ctrl-C to stop forwarding."
    kubectl -n monitoring port-forward svc/grafana 3000:3000 &
    kubectl -n monitoring port-forward svc/prometheus 9090:9090
    ;;
  status)
    kubectl -n monitoring get pods -o wide
    echo "--- Prometheus targets (operator should be UP) ---"
    echo "check http://localhost:9090/targets after 'open', or:"
    echo "  kubectl -n monitoring port-forward svc/prometheus 9090:9090"
    ;;
  down)
    kubectl delete namespace monitoring --ignore-not-found
    echo "✅ monitoring namespace deleted."
    ;;
  *)
    echo "usage: $0 {up|open|status|down}"; exit 1
    ;;
esac
