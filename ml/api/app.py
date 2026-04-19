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
S3_BUCKET = os.getenv("S3_BUCKET", "argus-models")
MODEL_KEY = os.getenv("MODEL_KEY", "spot_transformer.pt")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", None)  # Use http://host.docker.internal:4566 for localstack
FEATURES_CSV = os.getenv("FEATURES_CSV", "/app/data/features.csv")

# Global state
model = None
feature_cache = None
is_ready = False

num_features = 13
seq_len = 12

def _load_model():
    global model, is_ready
    try:
        model_path = "/tmp/model.pt"
        
        # In a real environment, you'd download the model from S3 on startup
        # For simplicity if local file exists (like mounted volume), we use it
        local_model_path = os.path.join(os.path.dirname(__file__), "../model/spot_transformer.pt")
        
        if os.path.exists(local_model_path):
            print(f"Loading model from local path: {local_model_path}")
            model_path = local_model_path
        else:
            print(f"Downloading model from s3://{S3_BUCKET}/{MODEL_KEY}")
            s3 = boto3.client('s3', endpoint_url=S3_ENDPOINT) if S3_ENDPOINT else boto3.client('s3')
            s3.download_file(S3_BUCKET, MODEL_KEY, model_path)
            
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
        local_features_path = os.path.join(os.path.dirname(__file__), "../data/features.csv")
        path_to_use = local_features_path if os.path.exists(local_features_path) else FEATURES_CSV
        
        df = pd.read_csv(path_to_use)
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
        raise HTTPException(status_code=503, detail="Model not ready")
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
