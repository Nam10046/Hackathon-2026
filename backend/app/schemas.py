"""Data shapes from CONTRACT.md. Change CONTRACT.md first, then this file."""
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str


class PredictRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class PredictResponse(BaseModel):
    label: str
    score: float = Field(ge=0, le=1)
    explanation: str
    model: str
