"""
Publishes risk events to the argus-risk-events SQS queue.

Local dev: queue is in LocalStack (AWS_ENDPOINT_URL=http://localhost:4566)
EKS prod:  queue is in real SQS, credentials via IRSA
"""

import json
import logging
import os

from controller.handlers import _boto3_client

logger = logging.getLogger(__name__)

QUEUE_URL = os.environ.get(
    "RISK_EVENTS_QUEUE_URL",
    "http://localhost:4566/000000000000/argus-risk-events",
)


def publish_risk_event(
    job_name: str,
    risk_score: float,
    instance_type: str,
    az: str,
    action: str = "checkpoint_and_migrate",
) -> None:
    """
    Sends a risk alert message to the SQS queue.

    action values (per contracts.md):
        checkpoint_and_migrate | checkpoint_only | monitor
    """
    import datetime

    message = {
        "job_name": job_name,
        "risk_score": risk_score,
        "instance_type": instance_type,
        "az": az,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "recommended_action": action,
    }

    sqs = _boto3_client("sqs")
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(message),
    )
    logger.info(f"[SQS] Published risk event for '{job_name}': score={risk_score}, action={action}")
