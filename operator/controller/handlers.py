"""
Argus Operator — kopf event handlers.

Week 4: stubs only.
Week 5: full reconcile loop — risk polling, checkpoint flush, cordon, reschedule, SQS.
"""

import logging
import os

import boto3
import httpx
import kopf

from controller import checkpoint, scheduler, sqs_publisher

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
    logger.info(f"[CREATE] SpotResilientJob '{name}' in namespace '{namespace}'")
    logger.info(f"  image:              {spec['image']}")
    logger.info(f"  checkpointPath:     {spec['checkpointPath']}")
    logger.info(f"  riskThreshold:      {spec.get('riskThreshold', RISK_THRESHOLD_DEFAULT)}")
    logger.info(f"  instanceFallback:   {spec['instanceFallback']}")

    patch.status["phase"] = "Running"
    patch.status["lastRiskScore"] = 0.0
    patch.status["lastCheckpointStep"] = 0


@kopf.on.update("argus.io", "v1", "spotresilientjobs")
def on_update(spec, name, namespace, old, new, diff, **kwargs):
    logger.info(f"[UPDATE] SpotResilientJob '{name}' updated")
    for op, field, old_val, new_val in diff:
        logger.info(f"  {op} {'.'.join(str(f) for f in field)}: {old_val!r} → {new_val!r}")


@kopf.on.delete("argus.io", "v1", "spotresilientjobs")
def on_delete(spec, name, namespace, **kwargs):
    logger.info(f"[DELETE] SpotResilientJob '{name}' deleted")
    logger.info(f"  Final checkpointPath: {spec['checkpointPath']}")


@kopf.timer("argus.io", "v1", "spotresilientjobs", interval=POLL_INTERVAL)
def reconcile(spec, name, namespace, status, patch, **kwargs):
    current_phase = status.get("phase", "Running")
    risk_threshold = spec.get("riskThreshold", RISK_THRESHOLD_DEFAULT)
    fallback_types = spec["instanceFallback"]
    checkpoint_path = spec["checkpointPath"]
    last_step = status.get("lastCheckpointStep", 0)
    instance_type = fallback_types[0]

    # Skip if already mid-migration
    if current_phase in ("Checkpointing", "Migrating"):
        logger.info(f"[RECONCILE] '{name}' skipped — already in phase '{current_phase}'")
        return

    # 1. Poll prediction service
    try:
        response = httpx.get(
            f"{PREDICT_SERVICE_URL}/predict",
            params={"instance_type": instance_type, "az": "eu-north-1a"},
            timeout=10.0,
        )
        response.raise_for_status()
        risk = response.json()
    except Exception as e:
        logger.warning(f"[RECONCILE] '{name}' — failed to reach predict service: {e}")
        return

    risk_score = risk["risk_score"]
    patch.status["lastRiskScore"] = risk_score

    logger.info(
        f"[RECONCILE] '{name}' | risk={risk_score:.3f} threshold={risk_threshold} "
        f"| phase={current_phase}"
    )

    if risk_score <= risk_threshold:
        return

    # 2. Risk exceeded — begin checkpoint + migrate sequence
    logger.warning(
        f"[RECONCILE] '{name}' risk {risk_score:.3f} > {risk_threshold} — triggering migration"
    )

    # Checkpoint
    patch.status["phase"] = "Checkpointing"
    next_step = last_step + 1
    try:
        checkpoint.flush_checkpoint(name, checkpoint_path, next_step)
        patch.status["lastCheckpointStep"] = next_step
        logger.info(f"[RECONCILE] '{name}' checkpoint flushed at step {next_step}")
    except Exception as e:
        logger.error(f"[RECONCILE] '{name}' checkpoint failed: {e}")
        patch.status["phase"] = "Failed"
        return

    # Publish SQS risk event
    try:
        sqs_publisher.publish_risk_event(
            job_name=name,
            risk_score=risk_score,
            instance_type=instance_type,
            az="eu-north-1a",
            action="checkpoint_and_migrate",
        )
    except Exception as e:
        logger.warning(f"[RECONCILE] '{name}' SQS publish failed (non-fatal): {e}")

    # Cordon node + reschedule pod
    patch.status["phase"] = "Migrating"
    try:
        node_name = scheduler.get_pod_node(name, namespace)
        if node_name:
            scheduler.cordon_node(node_name)
        scheduler.reschedule_pod(name, namespace, fallback_types)
    except Exception as e:
        logger.error(f"[RECONCILE] '{name}' reschedule failed: {e}")
        patch.status["phase"] = "Failed"
        return

    patch.status["phase"] = "Running"
    logger.info(f"[RECONCILE] '{name}' migration complete — back to Running")
