"""
Flushes a checkpoint to S3.

In production, Person B's training job writes the actual model.pt files.
The operator's role is to signal the training job to flush, then verify
the checkpoint appeared. For Week 5 integration testing, we write a
sentinel file to prove the S3 path and credentials work end-to-end.

Local dev: S3 is LocalStack (AWS_ENDPOINT_URL=http://localhost:4566)
EKS prod:  S3 is real AWS, credentials via IRSA
"""

import logging
import os

from controller.handlers import _boto3_client

logger = logging.getLogger(__name__)

CHECKPOINT_BUCKET = os.environ.get(
    "CHECKPOINT_BUCKET",
    "argus-checkpoints-844641713781",
)


def flush_checkpoint(job_name: str, checkpoint_path: str, step: int) -> str:
    """
    Writes a checkpoint sentinel to S3 at:
        s3://{bucket}/checkpoints/{job_name}/{step}/checkpoint.json

    In production this is triggered by signalling the training process.
    The training job (Person B) writes model.pt; this writes the metadata.

    Returns the S3 key of the written object.
    """
    import json
    import datetime

    s3 = _boto3_client("s3")

    # Derive bucket + prefix from the checkpointPath in the CRD spec
    # checkpointPath format: s3://{bucket}/checkpoints/{job-name}
    path_without_scheme = checkpoint_path.replace("s3://", "")
    bucket = path_without_scheme.split("/")[0]
    prefix = "/".join(path_without_scheme.split("/")[1:])

    key = f"{prefix}/{step}/checkpoint.json"
    metadata = {
        "job_name": job_name,
        "step": step,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "status": "flushed",
    }

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(metadata),
        ContentType="application/json",
    )

    # Update the 'latest' pointer
    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/latest",
        Body=str(step),
        ContentType="text/plain",
    )

    logger.info(f"[CHECKPOINT] Flushed '{job_name}' step={step} → s3://{bucket}/{key}")
    return f"s3://{bucket}/{key}"


def get_latest_step(checkpoint_path: str) -> int:
    """
    Reads the 'latest' pointer from S3. Returns 0 if no checkpoint exists yet.
    Used by the training job on startup to decide whether to resume.
    """
    s3 = _boto3_client("s3")

    path_without_scheme = checkpoint_path.replace("s3://", "")
    bucket = path_without_scheme.split("/")[0]
    prefix = "/".join(path_without_scheme.split("/")[1:])

    try:
        response = s3.get_object(Bucket=bucket, Key=f"{prefix}/latest")
        return int(response["Body"].read().decode("utf-8").strip())
    except s3.exceptions.NoSuchKey:
        return 0
    except Exception:
        return 0
