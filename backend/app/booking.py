"""Manual truck booking: only a PERSON books a truck (the system only sends a pickup_needed notice).
Needs a login: a customer sees and books only the compactors assigned to them; an admin sees and books all.
  GET  /book                 small HTML page with a "Book truck" button per compactor (embedded in Grafana "Site now")
  GET  /api/pickups/board    what that page shows: load, on-call %, open truck per compactor
  POST /api/pickups/book     {"compactor_id": "C1"} -> truck goes now: the board empties THAT compactor only
                             (pressing again while it is on its way re-sends the command)"""
import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from app import pickups
from app.db import compactor_status, compactors, get_engine
from app.access import Viewer, who_is_asking

router = APIRouter()
PAGE = pathlib.Path(__file__).parent / "static" / "book.html"


class BookIn(BaseModel):
    compactor_id: str
    booked_by: str = "operator"


@router.get("/book", include_in_schema=False)
def book_page():
    return FileResponse(PAGE, media_type="text/html")


@router.get("/api/pickups/board")
def board(v: Viewer = Depends(who_is_asking)):
    now = datetime.now(timezone.utc)
    out = []
    with get_engine().connect() as conn:
        rows = conn.execute(select(compactors, compactor_status.c.load_pct)
                            .select_from(compactors.outerjoin(compactor_status, compactors.c.id == compactor_status.c.compactor_id))
                            .order_by(compactors.c.id)).mappings().all()
        for c in rows:
            if v.devices is not None and c["id"] not in v.devices:   # a customer sees only their own compactors
                continue
            thr = c["on_call_threshold_pct"] or 80
            p = pickups._open(conn, c["id"])
            truck = None
            if p is not None and p["status"] == "booked":
                due = pickups._utc(p["truck_due"]) if p["truck_due"] else None
                truck = {"pickup_id": p["id"], "arrived": p["cmd_sent_at"] is not None, "late": bool(p["truck_late"]),
                         "arrives_in_site_h": round(pickups.site_h(due - now), 1) if due else None}
            load = c["load_pct"]
            out.append({"compactor_id": c["id"], "name": c["name"], "material": c["material"], "load_pct": load,
                        "on_call_pct": thr, "needs_truck": load is not None and load >= thr and truck is None, "truck": truck})
    return out


@router.post("/api/pickups/book")
def book(body: BookIn, v: Viewer = Depends(who_is_asking)):
    if v.devices is not None and body.compactor_id not in v.devices:
        raise HTTPException(404, f"Unknown compactor '{body.compactor_id}'")     # 404: do not reveal other customers' ids
    now = datetime.now(timezone.utc)
    with get_engine().begin() as conn:
        comp = conn.execute(select(compactors).where(compactors.c.id == body.compactor_id)).mappings().first()
        if comp is None:
            raise HTTPException(404, f"Unknown compactor '{body.compactor_id}'")
        pid, new = pickups.book(conn, dict(comp), now, by=(v.email or body.booked_by)[:60])
    return {"pickup_id": pid, "compactor_id": body.compactor_id, "status": "booked", "new": new}
