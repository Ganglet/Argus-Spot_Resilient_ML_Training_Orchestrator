"""
Argus Operator — kopf event handlers.

Week 4: stubs only — handlers register and log, no AWS calls yet.
Week 5: fill in reconcile loop (risk polling, checkpoint flush, cordon, reschedule).
"""

import logging
import os

import boto3
import kopf

PREDICT_SERVICE_URL = os.environ.get("PREDICT_SERVICE_URL", "http://localhost:8000")
RISK_THRESHOLD_DEFAULT = float(os.environ.get("RISK_THRESHOLD", "0.65"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))

# When AWS_ENDPOINT_URL is set (local dev via .env.local), boto3 hits LocalStack.
# On EKS (Week 6) the var is unset and boto3 hits real AWS via IRSA credentials.
_AWS_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL")

def _boto3_client(service: str):
    kwargs = {"region_name": os.environ.get("AWS_DEFAULT_REGION", "eu-north-1")}
    if _AWS_ENDPOINT:
        kwargs["endpoint_url"] = _AWS_ENDPOINT
    return boto3.client(service, **kwargs)

logger = logging.getLogger(__name__)


@kopf.on.create("argus.io", "v1", "spotresilientjobs")
def on_create(spec, name, namespace, patch, **kwargs):
    """
    Fires when a SpotResilientJob is created.
    Week 4: initialise status fields.
    Week 5: start the training pod.
    """
    logger.info(f"[CREATE] SpotResilientJob '{name}' in namespace '{namespace}'")
    logger.info(f"  image:              {spec['image']}")
    logger.info(f"  checkpointPath:     {spec['checkpointPath']}")
    logger.info(f"  riskThreshold:      {spec.get('riskThreshold', RISK_THRESHOLD_DEFAULT)}")
    logger.info(f"  instanceFallback:   {spec['instanceFallback']}")

    patch.status["phase"] = "Pending"
    patch.status["lastRiskScore"] = 0.0
    patch.status["lastCheckpointStep"] = 0


@kopf.on.update("argus.io", "v1", "spotresilientjobs")
def on_update(spec, name, namespace, old, new, diff, **kwargs):
    """
    Fires when a SpotResilientJob spec is updated.
    Week 4: log the diff.
    Week 5: handle riskThreshold changes mid-run.
    """
    logger.info(f"[UPDATE] SpotResilientJob '{name}' updated")
    for op, field, old_val, new_val in diff:
        logger.info(f"  {op} {'.'.join(field)}: {old_val!r} → {new_val!r}")


@kopf.on.delete("argus.io", "v1", "spotresilientjobs")
def on_delete(spec, name, namespace, **kwargs):
    """
    Fires when a SpotResilientJob is deleted.
    Week 4: log deletion.
    Week 5: clean up training pod + flush final checkpoint.
    """
    logger.info(f"[DELETE] SpotResilientJob '{name}' deleted")
    logger.info(f"  Final checkpointPath: {spec['checkpointPath']}")
    # TODO (Week 5): trigger final checkpoint flush before pod is removed


@kopf.timer("argus.io", "v1", "spotresilientjobs", interval=POLL_INTERVAL)
def reconcile(spec, name, namespace, status, patch, **kwargs):
    """
    Runs every POLL_INTERVAL seconds while the job is alive.
    Week 4: stub — logs that a poll cycle would happen.
    Week 5: call /predict, compare against riskThreshold, trigger action.
    """
    current_phase = status.get("phase", "Pending")
    risk_threshold = spec.get("riskThreshold", RISK_THRESHOLD_DEFAULT)
    instance_type = spec["instanceFallback"][0]  # primary instance type

    logger.info(
        f"[RECONCILE] '{name}' | phase={current_phase} | threshold={risk_threshold} "
        f"| predict_url={PREDICT_SERVICE_URL}"
    )

    # TODO (Week 5): replace stub with real reconcile logic
    #
    # risk = httpx.get(f"{PREDICT_SERVICE_URL}/predict",
    #                  params={"instance_type": instance_type, "az": "eu-north-1a"}).json()
    #
    # patch.status["lastRiskScore"] = risk["risk_score"]
    #
    # if risk["risk_score"] > risk_threshold:
    #     patch.status["phase"] = "Checkpointing"
    #     checkpoint.flush(name, spec["checkpointPath"])
    #     scheduler.cordon_node(node_name)
    #     scheduler.reschedule_pod(pod_spec, spec["instanceFallback"])
    #     sqs_publisher.publish(name, risk)
    #     patch.status["phase"] = "Migrating"
