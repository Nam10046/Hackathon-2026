"""Data shapes from CONTRACT.md. Change CONTRACT.md first, then this file."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadingIn(BaseModel):
    compactor_id: str
    weight_kg: float
    fill_pct: Optional[float] = Field(default=None, ge=0, le=100)
    ts: Optional[datetime] = None


class BulkReadingsIn(BaseModel):
    readings: list[ReadingIn]


class Alert(BaseModel):
    id: Optional[int] = None
    compactor_id: str
    ts: datetime
    type: str
    severity: str
    message: str


class Status(BaseModel):
    compactor_id: str
    name: str
    material: str
    weight_kg: Optional[float] = None
    fill_pct: Optional[float] = None
    load_pct: Optional[float] = None
    density_kg_m3: Optional[float] = None
    value_eur: Optional[float] = None
    co2_saved_kg: Optional[float] = None
    hours_to_full: Optional[float] = None
    last_ts: Optional[datetime] = None


class ReadingResult(BaseModel):
    reading_id: int
    alerts: list[Alert]
    status: Status
    duplicate: bool = False          # True = this exact reading was already stored (message sent twice)


class ReadingOut(BaseModel):
    ts: datetime
    weight_kg: float
    fill_pct: Optional[float] = None


class Material(BaseModel):
    name: str
    price_eur_per_kg: float
    density_min: float
    density_max: float
    co2_factor: float
