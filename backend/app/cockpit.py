"""Customer Value Cockpit API: recommended actions + human approval + evidence trail. Owner: backend person.

The cp_* tables are written by analytics/build_cockpit.py from the official Europress dataset.
The system only PROPOSES. A named person approves or rejects, can revert, and every decision is kept.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import inspect, insert, text

from app.db import action_decisions, get_engine
from app.security import require_key

router = APIRouter()
PAGE = Path(__file__).parent / "static" / "cockpit.html"

LATEST = """
SELECT a.*, d.decision AS decision, d.decided_by AS decided_by, d.note AS decision_note, d.decided_at AS decided_at
FROM cp_actions a
LEFT JOIN (
    SELECT ad.* FROM action_decisions ad
    JOIN (SELECT action_id, MAX(id) AS max_id FROM action_decisions GROUP BY action_id) m ON m.max_id = ad.id
) d ON d.action_id = a.action_id
"""


def _ready() -> bool:
    return inspect(get_engine()).has_table("cp_actions")


class DecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT", "REVERT"]
    decided_by: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


def _status(row: dict) -> str:
    d = row.get("decision")
    return "PENDING" if d in (None, "REVERT") else ("APPROVED" if d == "APPROVE" else "REJECTED")


@router.get("/api/cockpit/actions")
def list_actions(status: str | None = None, limit: int = 300):
    if not _ready():
        return []
    with get_engine().connect() as conn:
        rows = [dict(r) for r in conn.execute(text(LATEST + " ORDER BY a.flagged_invoice_eur DESC")).mappings()]
    for r in rows:
        r["status"] = _status(r)
    if status:
        rows = [r for r in rows if r["status"] == status.upper()]
    return rows[:limit]


@router.get("/api/cockpit/actions/{action_id}/evidence")
def evidence(action_id: str, limit: int = 25):
    """Trace a recommendation back to the source rows: findings for the same device, newest first."""
    if not _ready():
        raise HTTPException(404, "Cockpit not built yet — run analytics/build_cockpit.py")
    with get_engine().connect() as conn:
        act = conn.execute(text("SELECT * FROM cp_actions WHERE action_id = :a"), {"a": action_id}).mappings().first()
        if act is None:
            raise HTTPException(404, f"Unknown action '{action_id}'")
        flags = conn.execute(text(
            "SELECT entity_type, entity_id, label_family, found_at, explanation, evidence, eur_at_stake, evidence_tag "
            "FROM cp_flags WHERE device_id = :d ORDER BY found_at DESC LIMIT :n"),
            {"d": act["device_id"], "n": limit}).mappings().all()
        history = conn.execute(
            action_decisions.select().where(action_decisions.c.action_id == action_id).order_by(action_decisions.c.id)
        ).mappings().all()
    return {"action": dict(act), "findings": [dict(f) for f in flags], "decision_history": [dict(h) for h in history]}


@router.post("/api/cockpit/actions/{action_id}/decision", dependencies=[Depends(require_key)])
def decide(action_id: str, body: DecisionIn):
    if not _ready():
        raise HTTPException(404, "Cockpit not built yet — run analytics/build_cockpit.py")
    with get_engine().begin() as conn:
        if conn.execute(text("SELECT 1 FROM cp_actions WHERE action_id = :a"), {"a": action_id}).first() is None:
            raise HTTPException(404, f"Unknown action '{action_id}'")
        conn.execute(insert(action_decisions).values(
            action_id=action_id, decision=body.decision, decided_by=body.decided_by, note=body.note,
            decided_at=datetime.now(timezone.utc)))
    return {"action_id": action_id, "decision": body.decision, "status": _status({"decision": body.decision})}


@router.get("/cockpit", response_class=HTMLResponse, include_in_schema=False)
def page():
    return PAGE.read_text(encoding="utf-8")
