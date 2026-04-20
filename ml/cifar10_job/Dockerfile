FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY train.py .

# Optional environment variables
ENV S3_BUCKET=argus-checkpoints-844641713781
ENV S3_PREFIX=checkpoints/cifar10-test/latest_checkpoint.pt
ENV EPOCHS=5

CMD ["python", "train.py"]
