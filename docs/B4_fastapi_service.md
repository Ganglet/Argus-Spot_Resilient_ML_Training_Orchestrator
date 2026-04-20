# FastAPI Prediction Service

**Phase:** Week 4 — API & Dockerization  
**Owner:** Person B  
**Status:** Complete — FastAPI service built, dockerized, load-tested, and prepared for ECR.

---

## Objective

Expose the trained PyTorch Transformer model via a highly performant REST API. The Kubernetes Operator (Person A's layer) will poll this `/predict` endpoint every 60 seconds to determine if a running Spot instance is at risk of being interrupted.

---

## What Was Done

1. **`app.py` (FastAPI + Uvicorn)**: Built a lightweight asynchronous API that accepts an EC2 instance type and Availability Zone, fetches the required time-series context, runs inference through the `spot_transformer.pt` model, and returns a `risk_score` float between 0 and 1.
2. **Dockerization**: Packaged the API, the model artifact, and PyTorch dependencies into a standalone Linux container using `ml/api/Dockerfile`.
3. **Load Testing**: Wrote a `load_test.py` script using `concurrent.futures` to hammer the API with requests and ensure it can handle the load of hundreds of concurrent Operator reconcilation loops.
4. **Health Probes**: Added a `/health` endpoint to satisfy Kubernetes Liveness and Readiness probes.

---

## Commands

```bash
# Run the API locally for development
cd ml/api
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Build the Docker image
docker build -t argus/predict-service:latest ml/api/

# Run the load test against a running local API
python ml/api/load_test.py
```

---

## Why (Key Decisions)

**Why FastAPI?**  
FastAPI natively supports `async`/`await` and uses Pydantic for strict standard data validation (matching our integration contract shape in `docs/contracts.md`). It is remarkably faster than standard Flask, which is critical because our API serves as a bottleneck for the entire Kubernetes Operator polling loop.

**Why include the model in the container instead of loading it dynamically?**  
Loading a 5MB `.pt` file from S3 on every spin-up delays horizontal autoscaling. Because the model binary is small, we `COPY` it directly into the Docker image, allowing the Pod to achieve a "Ready" state in less than 2 seconds.

---

## Outputs

| Output | Description |
|--------|-------------|
| `ml/api/app.py` | FastAPI application code. |
| `ml/api/Dockerfile` | Docker definition for the `argus/predict-service` image. |
| `ml/api/load_test.py` | Asynchronous benchmarking script. |
| `ml/api/requirements.txt` | Python dependencies (fastapi, uvicorn, torch). |
