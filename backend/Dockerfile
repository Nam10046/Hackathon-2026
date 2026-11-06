# Build context = repo root (so trained models in models/ are baked into the image for Rahti).
# Runs as any user ID (OpenShift/Rahti requirement): nothing here needs root.
FROM python:3.12-slim
WORKDIR /code
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY models /models
ENV MODELS_DIR=/models
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
