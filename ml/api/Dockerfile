FROM python:3.11-slim-bookworm

WORKDIR /app

COPY ml/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ml/model/transformer.py /app/model/transformer.py
COPY ml/model/spot_transformer.pt /app/model/spot_transformer.pt
COPY ml/data/features.csv /app/data/features.csv
COPY ml/api/app.py /app/api/app.py

ENV PYTHONPATH="/app/model"

EXPOSE 8000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
