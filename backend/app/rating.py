"""A PERSON rates the waste company after each lift: things the sensor cannot know.
  - truck on time?        did the truck come when it was booked?
  - weighbridge on time?  did the waste company send the weighbridge ticket (their weight) on time?
Same login as the Book truck panel: the Portal session, or a Grafana login in the admin org. A customer rates only
their own compactors' lifts. The scores per waste company are on Analysis > 3 Waste companies.
  GET /rate                          small HTML page (embedded in Grafana "Pickups")
  GET /api/pickups/ratings?limit=20  latest finished lifts with their rating (null = not rated yet)
  PUT /api/pickups/{id}/rating       {"truck_on_time": true, "weighbridge_on_time": false, "note": "..."}
                                     send only what you rate; null clears an answer"""
import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.access import Viewer, portal_or_grafana
from app.db import compactors, get_engine, pickups

router = APIRouter()
PAGE = pathlib.Path(__file__).parent / "static" / "rate.html"
FIELDS = ["truck_on_time", "weighbridge_on_time", "rating_note", "rated_by", "rated_at"]


class RatingIn(BaseModel):
    truck_on_time: bool | None = None
    weighbridge_on_time: bool | None = None
    note: str | None = Field(default=None, max_length=300)


def _row(r):
    d = dict(r)
    d["rated_at"] = d["rated_at"].isoformat() if d["rated_at"] else None
    d["done_at"] = d["done_at"].isoformat() if d.get("done_at") else None
    return d


def _query():
    return (select(pickups.c.id, pickups.c.compactor_id, pickups.c.done_at, pickups.c.kind, pickups.c.load_before_pct,
                   pickups.c.kg_collected, pickups.c.verdict, compactors.c.material, compactors.c.operator_name,
                   *[pickups.c[f] for f in FIELDS])
            .select_from(pickups.join(compactors, compactors.c.id == pickups.c.compactor_id))
            .where(pickups.c.status == "done"))


@router.get("/rate", include_in_schema=False)
def rate_page():
    return FileResponse(PAGE, media_type="text/html")


@router.get("/api/pickups/ratings")
def list_ratings(limit: int = Query(20, ge=1, le=200), v: Viewer = Depends(portal_or_grafana)):
    q = _query().order_by(pickups.c.done_at.desc()).limit(limit)
    if v.devices is not None:                       # a customer sees only their own compactors
        q = q.where(pickups.c.compactor_id.in_(list(v.devices) or [""]))
    with get_engine().connect() as conn:
        return [_row(r) for r in conn.execute(q).mappings()]


@router.put("/api/pickups/{pickup_id}/rating")
def rate(pickup_id: int, body: RatingIn, v: Viewer = Depends(portal_or_grafana)):
    sent = body.model_fields_set                    # only change what was sent: rate one question at a time
    vals = {f: getattr(body, f) for f in ("truck_on_time", "weighbridge_on_time") if f in sent}
    if "note" in sent:
        vals["rating_note"] = (body.note or "").strip() or None
    if not vals:
        raise HTTPException(422, "Send truck_on_time, weighbridge_on_time or note")
    with get_engine().begin() as conn:
        p = conn.execute(_query().where(pickups.c.id == pickup_id)).mappings().first()
        if p is None or (v.devices is not None and p["compactor_id"] not in v.devices):
            raise HTTPException(404, f"Unknown pickup {pickup_id}")      # 404: do not reveal other customers' lifts
        conn.execute(update(pickups).where(pickups.c.id == pickup_id).values(
            **vals, rated_by=(v.email or v.role)[:60], rated_at=datetime.now(timezone.utc)))
        return _row(conn.execute(_query().where(pickups.c.id == pickup_id)).mappings().first())
