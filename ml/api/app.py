from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import boto3
import torch
import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timezone

# Add the model directory to sys.path so we can import the model class
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../model')))
from transformer import SpotInterruptionPredictor

app = FastAPI(title="Argus Spot Prediction Service")

# Configuration
MOCK_MODE = os.environ.get('MOCK_MODE') == 'true'
FEATURES_CSV = os.getenv("FEATURES_CSV", "/app/data/features.csv")

# Global state
model = None
feature_cache = None
is_ready = False

num_features = 13
seq_len = 12

def _load_model():
    global model, is_ready
    
    if MOCK_MODE:
        print("MOCK_MODE is enabled. Skipping PyTorch model load entirely.")
        is_ready = True
        return
        
    try:
        # Load from local filepath or default to the relative path
        model_path = os.getenv("MODEL_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "../model/spot_transformer.pt")))
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at {model_path}")
        print(f"Loading model from local path: {model_path}")
        model = SpotInterruptionPredictor(num_features=num_features, d_model=128, nhead=4, num_layers=4)
        model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
        model.eval()
        is_ready = True
        print("Model loaded successfully.")
    except Exception as e:
        print(f"Error loading model: {e}")
        is_ready = False

def _load_features():
    global feature_cache
    try:
        # Load features from env variable or relative path
        features_path = os.getenv("FEATURES_CSV", os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/features.csv")))
        if not os.path.exists(features_path):
            raise FileNotFoundError(f"Features file not found at {features_path}")
        df = pd.read_csv(features_path)
        # Select numeric columns
        numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
        cache = {}
        for (instance_type, az), group in df.groupby(['instance_type', 'availability_zone']):
            # Sort by timestamp to get the latest 12 sequences
            sorted_group = group.sort_values('timestamp')
            recent_data = sorted_group[numeric_cols].values[-seq_len:]
            # If not enough data, we pad with zeros (or mean, but zeroes for simplicity here)
            if len(recent_data) < seq_len:
                pad_size = seq_len - len(recent_data)
                padding = np.zeros((pad_size, num_features))
                recent_data = np.vstack([padding, recent_data])
            cache[(instance_type, az)] = recent_data
        feature_cache = cache
        print(f"Loaded features for {len(feature_cache)} (instance_type, az) combinations.")
    except Exception as e:
        print(f"Error loading features: {e}")
        feature_cache = {}

@app.on_event("startup")
async def startup_event():
    _load_model()
    _load_features()

@app.get("/health")
def health_check():
    if not is_ready:
        return {"status": "ok", "detail": "Model not ready (running in degraded mode for local testing)"}
    return {"status": "ok"}

class PredictRequest(BaseModel):
    instance_type: str
    az: str

@app.post("/predict")
def predict_post(req: PredictRequest):
    return _predict(req.instance_type, req.az)

@app.get("/predict")
def predict_get(instance_type: str, az: str):
    return _predict(instance_type, az)

def _predict(instance_type: str, az: str):
    if not is_ready:
        raise HTTPException(status_code=503, detail="Model not ready")
        
    if MOCK_MODE:
        return {
            "instance_type": instance_type,
            "az": az,
            "risk_score": 0.42,  # Dummy safe score
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mock_mode": True
        }
        
    key = (instance_type, az)
    if key not in feature_cache:
        raise HTTPException(status_code=404, detail="No historical features found for this instance type & AZ")
        
    recent_features = feature_cache[key]
    
    # Convert to tensor [batch=1, seq_len=12, num_features=13]
    x_tensor = torch.tensor(recent_features, dtype=torch.float32).unsqueeze(0)
    
    with torch.no_grad():
        logits = model(x_tensor)
        risk_score = torch.sigmoid(logits).item()
        
    return {
        "instance_type": instance_type,
        "az": az,
        "risk_score": round(risk_score, 4),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
