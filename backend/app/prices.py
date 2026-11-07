"""Customer prices for the LIVE page, kept simple: 2 numbers per material, typed in by the customer.
  GET /prices                      small HTML form (embedded in Grafana "Money & CO2")
  PUT /api/materials/{name}        {"lift_fee_eur": 45, "price_eur_per_t": 80}  (signed-in admin: prices apply to everyone)
       lift_fee_eur     cost per lift (lift fee + transport)
       price_eur_per_t  + the waste company pays you per tonne, - you pay them
The detailed invoice formula is on the Analysis pages (real invoice lines)."""
import pathlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.db import get_engine, materials
from app.auth import require_admin

router = APIRouter()
PAGE = pathlib.Path(__file__).parent / "static" / "prices.html"


class PriceIn(BaseModel):
    lift_fee_eur: float = Field(ge=0, le=10000)          # cost per lift
    price_eur_per_t: float = Field(ge=-5000, le=5000)    # + they pay you, - you pay them


@router.get("/prices", include_in_schema=False)
def prices_page():
    return FileResponse(PAGE, media_type="text/html")


@router.put("/api/materials/{name}", dependencies=[Depends(require_admin)])
def set_price(name: str, body: PriceIn):
    with get_engine().begin() as conn:
        n = conn.execute(update(materials).where(materials.c.name == name)
                         .values(lift_fee_eur=body.lift_fee_eur, price_eur_per_kg=body.price_eur_per_t / 1000)).rowcount
        if not n:
            raise HTTPException(404, f"Unknown material '{name}'")
        return dict(conn.execute(select(materials).where(materials.c.name == name)).mappings().first())
