"""Backend API. Owner: backend person. Endpoints must match CONTRACT.md."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.service import predict
from app.schemas import HealthResponse, PredictRequest, PredictResponse

app = FastAPI(title="Hackathon 2026 API", version=os.getenv("APP_VERSION", "0.1.0"))

# Lets the frontend call the API when opened as a plain file or from another port
origins = os.getenv("CORS_ORIGINS", "http://localhost:8080,null").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "version": app.version}


@app.post("/api/predict", response_model=PredictResponse)
def predict_endpoint(req: PredictRequest):
    # The AI module does the real work; the backend just validates and passes data
    return predict(req.text)
