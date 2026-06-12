# Week 6 Real Services - Build and Push Guide

This branch (`week6-real-services`) contains scripts to build and push the real predict service and CIFAR-10 training job images to ECR.

## Summary of Changes

### 1. FastAPI Service - MOCK_MODE Status
The FastAPI service in `ml/api/app.py` is **already using real model prediction**:
- Loads the real Transformer model from S3 or local path
- Uses actual feature data from `features.csv`
- No MOCK_MODE flag exists in the service
- The separate `operator/controller/mock_predict.py` is a standalone mock service for local testing only

### 2. New Build Scripts Created

#### Bash Scripts (for Linux/Mac/WSL):
- `scripts/push_predict_service.sh` - Build and push predict service image
- `scripts/push_training_job.sh` - Build and push training job image
- `scripts/push_operator.sh` - Already exists (for reference)
- `scripts/build_and_push_all.sh` - Build and push all three images

#### Windows Batch Scripts:
- `scripts/push_predict_service.bat` - Build and push predict service image
- `scripts/push_training_job.bat` - Build and push training job image
- `scripts/push_operator.bat` - Build and push operator image
- `scripts/build_and_push_all.bat` - Build and push all three images

## Prerequisites

1. **AWS CLI** configured with credentials:
   ```bash
   aws configure
   ```

2. **Docker** installed and running

3. **ECR Repositories** created via Terraform:
   - `argus/predict-service`
   - `argus/training-job`
   - `argus/operator`

## Usage

### Option 1: Build and Push All Images at Once

**On Windows:**
```cmd
scripts\build_and_push_all.bat latest
```

**On Linux/Mac/WSL:**
```bash
bash scripts/build_and_push_all.sh latest
```

### Option 2: Build Individual Images

**Predict Service:**
```cmd
# Windows
scripts\push_predict_service.bat latest

# Linux/Mac/WSL
bash scripts/push_predict_service.sh latest
```

**Training Job:**
```cmd
# Windows
scripts\push_training_job.bat latest

# Linux/Mac/WSL
bash scripts/push_training_job.sh latest
```

**Operator:**
```cmd
# Windows
scripts\push_operator.bat latest

# Linux/Mac/WSL
bash scripts/push_operator.sh latest
```

## ECR Repository URLs

Based on account `844641713781` in region `eu-north-1`:

- **Predict Service**: `844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/predict-service:latest`
- **Training Job**: `844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/training-job:latest`
- **Operator**: `844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/operator:latest`

## Image Details

### 1. Predict Service (`argus/predict-service`)
- **Context**: Root directory (`.`)
- **Dockerfile**: `ml/api/Dockerfile`
- **Contents**:
  - FastAPI application (`ml/api/app.py`)
  - Transformer model (`ml/model/transformer.py`, `ml/model/spot_transformer.pt`)
  - Feature data (`ml/data/features.csv`)
- **Base Image**: `python:3.11-slim-bookworm`
- **Exposed Port**: 8000

### 2. Training Job (`argus/training-job`)
- **Context**: `ml/cifar10_job/`
- **Dockerfile**: `ml/cifar10_job/Dockerfile`
- **Contents**:
  - Training script (`train.py`)
  - Dependencies (PyTorch, boto3)
- **Base Image**: `python:3.10-slim`
- **Environment Variables**:
  - `S3_BUCKET=argus-checkpoints-844641713781`
  - `S3_PREFIX=checkpoints/cifar10-test/latest_checkpoint.pt`
  - `EPOCHS=5`

### 3. Operator (`argus/operator`)
- **Context**: `operator/`
- **Dockerfile**: `operator/Dockerfile`
- **Contents**:
  - Kopf-based operator controllers
  - Checkpoint, scheduler, handlers modules
  - RBAC and CRD definitions

## Troubleshooting

### Docker Login Issues
If you get authentication errors:
```bash
aws ecr get-login-password --region eu-north-1 | docker login --username AWS --password-stdin 844641713781.dkr.ecr.eu-north-1.amazonaws.com
```

### Build Context Issues for Predict Service
The predict service Dockerfile references files from multiple `ml/` subdirectories, so it **must** be built from the repository root:
```bash
docker build -t IMAGE_NAME -f ml/api/Dockerfile .
```

### Verify Images Locally
```bash
# List built images
docker images | grep argus

# Test predict service locally
docker run -p 8000:8000 844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/predict-service:latest

# Test training job locally
docker run 844641713781.dkr.ecr.eu-north-1.amazonaws.com/argus/training-job:latest
```

## Next Steps

After pushing images to ECR:

1. **Update Kubernetes manifests** to reference ECR images:
   - `k8s/predict-service.yaml`
   - `demo/spotresilientjob.yaml` (training job)
   - `helm/argus/values.yaml` (operator)

2. **Deploy to EKS**:
   ```bash
   kubectl apply -f k8s/predict-service.yaml
   kubectl apply -f demo/spotresilientjob.yaml
   ```

3. **Verify deployments**:
   ```bash
   kubectl get pods
   kubectl logs <pod-name>
   ```

4. **Test predict service**:
   ```bash
   kubectl port-forward service/predict-service 8000:8000
   curl "http://localhost:8000/predict?instance_type=m5.large&az=eu-north-1a"
   ```

## Week 6 Blueprint Completion

- ✅ FastAPI service using real model (no MOCK_MODE)
- ✅ Build scripts for predict-service image
- ✅ Build scripts for training-job image
- ✅ Both Bash and Windows batch script versions
- ⏳ Push images to ECR (run the scripts)
- ⏳ Deploy to EKS
- ⏳ Test real Spot interruption

## Notes

- The predict service already loads the real Transformer model and makes real predictions
- `mock_predict.py` in the operator is a separate standalone service for local testing only
- All scripts default to `latest` tag but accept custom tags as first argument
- Images are scanned automatically on push (configured in ECR)
- ECR lifecycle policy keeps only the last 5 images per repository
