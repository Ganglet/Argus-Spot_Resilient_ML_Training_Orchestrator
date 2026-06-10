"""
Mock FastAPI prediction service for local operator testing.

Runs independently of Person B's real service. Returns a configurable
risk score so you can test the full operator control loop without
needing the real ML model running.

Usage:
    pip install fastapi uvicorn
    MOCK_RISK_SCORE=0.9 uvicorn controller.mock_predict:app --port 8000

Then set PREDICT_SERVICE_URL=http://localhost:8000 in .env.local.
To test high-risk path: MOCK_RISK_SCORE=0.9 (above default threshold 0.65)
To test low-risk path:  MOCK_RISK_SCORE=0.3
"""

import datetime
import os

from fastapi import FastAPI

app = FastAPI(title="Argus Mock Predict Service")

MOCK_RISK_SCORE = float(os.environ.get("MOCK_RISK_SCORE", "0.9"))


@app.get("/predict")
def predict(instance_type: str = "m5.large", az: str = "eu-north-1a"):
    return {
        "instance_type": instance_type,
        "az": az,
        "risk_score": MOCK_RISK_SCORE,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
