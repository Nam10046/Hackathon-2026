"""Analysis API on the LIVE data of our customers (the ESP32 site is the demo customer): pickups the board measured,
problems it found, invoices the customer types in, the check of each invoice against the measurement, and decisions.
(The Europress dataset is only used to TRAIN the models; it is not shown here.)

Everything needs a login (app/auth.py). Admin sees every customer; a customer sees ONLY the compactors assigned to
their tenant and that tenant's invoices (app/access.py). Writes are protected by the login session, not by a key.
  GET  /api/analysis/summary                       lifts, kg, verdicts, issues, estimated cost, invoices to check, € overcharged
  GET  /api/analysis/customers | /operators        names this viewer may see
  GET  /api/analysis/problems?limit=100            issues, newest first: lifts too early / too late (one per lift) and
                                                   device faults (same fault, same compactor, same hour = one)
  GET  /api/analysis/pickups?limit=200             every measured lift with its live cost estimate
  GET  /api/analysis/invoices?status=waiting       invoices + check result + latest decision
  GET  /api/analysis/invoices/draft?operator=&period_from=&period_to=   the invoice the board's data says you should get
  POST /api/analysis/invoices                      type in an invoice {invoice_id, operator_name, period_from, period_to,
                                                   total_eur, entered_by, lines: [...]} -> stored and checked at once
  GET  /api/analysis/invoices/{id}                 one invoice with its checked lines and decision history
  POST /api/analysis/invoices/{id}/check           run the check again (e.g. after new pickups or new prices)
  POST /api/analysis/invoices/{id}/decision        {"decision": "APPROVE"|"REJECT"|"HOLD", "decided_by", "note"}
  GET  /invoices                                   page: enter an invoice, see the comparison, decide (Grafana embed)"""
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import insert, select, text

from app import invoice_check
from app.access import Viewer, who_is_asking
from app.db import DEMO_CUSTOMER, compactors, get_engine, invoice_decisions, invoice_lines, invoices

router = APIRouter()
PAGE = Path(__file__).parent / "static" / "invoices.html"

# newest decision per invoice (portable SQL: PostgreSQL and SQLite)
LATEST = ("LEFT JOIN (SELECT d.* FROM invoice_decisions d JOIN (SELECT invoice_id, MAX(id) AS max_id FROM invoice_decisions "
          "GROUP BY invoice_id) m ON m.max_id = d.id) d ON d.invoice_id = i.invoice_id")
STATUS = {"waiting": "d.decision IS NULL", "approved": "d.decision = 'APPROVE'", "rejected": "d.decision = 'REJECT'",
          "hold": "d.decision = 'HOLD'", "all": "1 = 1"}
# An ISSUE is something a person should look at, counted once:
#   - a LIFT judged too early or too late (one issue per lift, from the board's own measurement)
#   - a DEVICE / DATA fault, the same fault on the same compactor within one hour counted once
# AI lift-model alerts are a second opinion on a lift, not an extra issue (they stay in the event log).
DEVICE_TYPES = ("spike", "sensor_stuck", "sensor_fault", "data_gap", "zero_shift", "overload", "unexpected_drop",
                "signature_invalid", "contamination")
LIFT_PROBLEM = {"TOO_EARLY": "emptied too early", "TOO_LATE": "left full too long"}


def _issues(w, p, limit=None):
    """Issues for the rows this viewer may see, newest first (grouping in Python keeps the SQL portable)."""
    lifts = _rows("SELECT p.done_at AS ts, p.compactor_id, c.customer_name, c.operator_name, p.verdict, p.verdict_reason "
                  "FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
                  f"WHERE p.status = 'done' AND p.verdict IN ('TOO_EARLY', 'TOO_LATE') AND {w}", p)
    out = [{"ts": r["ts"], "compactor_id": r["compactor_id"], "customer_name": r["customer_name"], "operator_name": r["operator_name"],
            "kind": "lift", "problem": LIFT_PROBLEM[r["verdict"]], "what": r["verdict_reason"], "times": 1} for r in lifts]
    dev = _rows("SELECT a.ts, a.compactor_id, c.customer_name, c.operator_name, a.type, a.message FROM alerts a "
                f"JOIN compactors c ON c.id = a.compactor_id WHERE a.type IN ({', '.join(repr(x) for x in DEVICE_TYPES)}) AND {w} "
                "ORDER BY a.ts", p)
    groups = {}
    for r in dev:
        ts = r["ts"] if isinstance(r["ts"], datetime) else datetime.fromisoformat(str(r["ts"]))
        key = (r["compactor_id"], r["type"], ts.strftime("%Y-%m-%d %H"))
        if key in groups:
            groups[key]["times"] += 1
        else:
            groups[key] = {"ts": r["ts"], "compactor_id": r["compactor_id"], "customer_name": r["customer_name"],
                           "operator_name": r["operator_name"], "kind": "device", "problem": r["type"].replace("_", " "),
                           "what": r["message"], "times": 1}
    out += list(groups.values())
    out.sort(key=lambda x: str(x["ts"]), reverse=True)
    return out[:limit] if limit else out


class LineIn(BaseModel):
    line_type: Literal["LIFT_FEE", "PROCESSING", "MATERIAL_CREDIT", "HAULAGE", "SURCHARGE", "PENALTY", "OTHER"]
    compactor_id: str | None = None
    service_date: date | None = None
    quantity: float | None = Field(default=None, ge=0)
    unit: Literal["lift", "t", "kg", "pcs"] | None = None
    unit_price_eur: float | None = None
    amount_eur: float                               # + charge, - credit


class InvoiceIn(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=60)
    operator_name: str = Field(min_length=1, max_length=80)
    period_from: date
    period_to: date
    total_eur: float
    entered_by: str = Field(min_length=2, max_length=80)
    customer_name: str | None = None                # admin only; a customer always enters for themselves
    lines: list[LineIn] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _period(self):
        if self.period_to < self.period_from:
            raise ValueError("period_to is before period_from")
        return self


class InvoiceDecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT", "HOLD"]
    decided_by: str = Field(min_length=2, max_length=80)
    note: str | None = Field(default=None, max_length=500)


def _scope(v: Viewer, col: str):
    """SQL filter + parameters for what this viewer may see (admin: everything).
    Invoices (i.customer_name) belong to the customer's tenant; compactor data (c.customer_name / customer_name on the
    compactors table) is limited to the devices an admin assigned to that tenant (tenant_devices)."""
    if v.is_admin:
        return "1 = 1", {}
    if col.startswith("i."):
        return f"{col} = :customer", {"customer": v.customer}
    id_col = "c.id" if col.startswith("c.") else "id"
    devices = sorted(v.devices or [])
    if not devices:
        return "1 = 0", {}
    names = [f"dev{i}" for i in range(len(devices))]
    return f"{id_col} IN ({', '.join(':' + n for n in names)})", dict(zip(names, devices))


def _rows(sql, params=None):
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings()]


PICKUP_COST = ("coalesce(m.lift_fee_eur, p.fee_eur, 0) - p.kg_collected * m.price_eur_per_kg")   # live estimate (app/pickups.costs)
PICKUPS = ("FROM pickups p JOIN compactors c ON c.id = p.compactor_id JOIN materials m ON m.name = c.material "
           "WHERE p.status = 'done'")


@router.get("/api/analysis/summary")
def summary(v: Viewer = Depends(who_is_asking)):
    w, p = _scope(v, "c.customer_name")
    lifts = _rows("SELECT count(*) AS lifts, sum(p.kg_collected) AS kg, "
                  "sum(CASE WHEN p.verdict = 'ON_TIME' THEN 1 ELSE 0 END) AS on_time, "
                  "sum(CASE WHEN p.verdict = 'TOO_EARLY' THEN 1 ELSE 0 END) AS too_early, "
                  "sum(CASE WHEN p.verdict = 'TOO_LATE' THEN 1 ELSE 0 END) AS too_late, "
                  f"sum({PICKUP_COST}) AS estimated_cost_eur {PICKUPS} AND {w}", p)[0]
    t = (lifts["kg"] or 0) / 1000
    lifts["estimated_cost_eur_per_t"] = round(lifts["estimated_cost_eur"] / t, 1) if t and lifts["estimated_cost_eur"] is not None else None
    issues = _issues(w, p)
    probs = {"issues": len(issues), "lift_issues": sum(i["kind"] == "lift" for i in issues),
             "device_issues": sum(i["kind"] == "device" for i in issues)}
    wi, pi = _scope(v, "i.customer_name")
    inv = _rows("SELECT count(*) AS invoices, coalesce(sum(CASE WHEN d.decision IS NULL THEN 1 ELSE 0 END), 0) AS waiting, "
                "coalesce(sum(CASE WHEN d.decision IS NULL AND i.suggestion = 'CHECK' THEN 1 ELSE 0 END), 0) AS to_check, "
                "coalesce(sum(i.overcharged_eur), 0) AS overcharged_eur, coalesce(sum(i.unverified_eur), 0) AS unverified_eur, "
                "coalesce(sum(i.total_eur), 0) AS billed_eur "
                f"FROM invoices i {LATEST} WHERE {wi}", pi)[0]
    return {"scope": "all customers" if v.is_admin else v.customer, **lifts, **probs, **inv}


@router.get("/api/analysis/customers")
def customers(v: Viewer = Depends(who_is_asking)):
    if not v.is_admin:
        return [v.customer]
    return [r["customer_name"] for r in _rows("SELECT DISTINCT customer_name FROM compactors WHERE customer_name IS NOT NULL ORDER BY 1")]


@router.get("/api/analysis/operators")
def operators(v: Viewer = Depends(who_is_asking)):
    w, p = _scope(v, "customer_name")
    return [r["operator_name"] for r in _rows(f"SELECT DISTINCT operator_name FROM compactors WHERE operator_name IS NOT NULL AND {w} ORDER BY 1", p)]


@router.get("/api/analysis/problems")
def problems(limit: int = Query(100, ge=1, le=1000), v: Viewer = Depends(who_is_asking)):
    w, p = _scope(v, "c.customer_name")
    return _issues(w, p, limit)


@router.get("/api/analysis/pickups")
def list_pickups(limit: int = Query(200, ge=1, le=2000), v: Viewer = Depends(who_is_asking)):
    w, p = _scope(v, "c.customer_name")
    return _rows("SELECT p.id, p.done_at, p.compactor_id, c.customer_name, c.operator_name, c.material, p.kind, p.load_before_pct, "
                 f"p.kg_collected, p.verdict, p.verdict_reason, p.co2_kg, {PICKUP_COST} AS estimated_cost_eur "
                 f"{PICKUPS} AND {w} ORDER BY p.done_at DESC LIMIT :limit", {**p, "limit": limit})


@router.get("/api/analysis/invoices")
def list_invoices(status: str = "waiting", limit: int = Query(100, ge=1, le=1000), customer: str | None = None,
                  v: Viewer = Depends(who_is_asking)):
    if status not in STATUS:
        raise HTTPException(400, f"status must be one of {', '.join(STATUS)}")
    w, p = _scope(v, "i.customer_name")
    if customer and v.is_admin:                       # admin can look up one customer
        w, p = "i.customer_name = :customer", {"customer": customer}
    return _rows("SELECT i.*, d.decision, d.decided_by, d.note AS decision_note, d.decided_at "
                 f"FROM invoices i {LATEST} WHERE ({w}) AND {STATUS[status]} "
                 "ORDER BY CASE WHEN i.suggestion = 'CHECK' THEN 0 ELSE 1 END, i.entered_at DESC LIMIT :limit", {**p, "limit": limit})


def _customer_for(v: Viewer, asked: str | None) -> str:
    return (asked or DEMO_CUSTOMER) if v.is_admin else v.customer


@router.get("/api/analysis/invoices/draft")
def draft(operator: str, period_from: date, period_to: date, customer: str | None = None, v: Viewer = Depends(who_is_asking)):
    with get_engine().connect() as conn:
        return invoice_check.draft_from_measurement(conn, _customer_for(v, customer), operator, period_from, period_to)


@router.post("/api/analysis/invoices")
def enter_invoice(body: InvoiceIn, v: Viewer = Depends(who_is_asking)):
    cust = _customer_for(v, body.customer_name)
    with get_engine().begin() as conn:
        if conn.execute(select(invoices.c.invoice_id).where(invoices.c.invoice_id == body.invoice_id)).first():
            raise HTTPException(409, f"Invoice '{body.invoice_id}' is already entered")
        if not conn.execute(select(compactors.c.id).where(compactors.c.customer_name == cust)).first():
            raise HTTPException(404, f"Unknown customer '{cust}'")
        conn.execute(insert(invoices).values(
            invoice_id=body.invoice_id, customer_name=cust, operator_name=body.operator_name, period_from=body.period_from,
            period_to=body.period_to, total_eur=body.total_eur, entered_by=body.entered_by.strip(), entered_at=datetime.now(timezone.utc)))
        conn.execute(insert(invoice_lines), [{"invoice_id": body.invoice_id, "line_no": i, **ln.model_dump()}
                                             for i, ln in enumerate(body.lines, 1)])
        return invoice_check.check(conn, body.invoice_id)


def _one_invoice(invoice_id: str, v: Viewer):
    w, p = _scope(v, "i.customer_name")
    rows = _rows(f"SELECT i.*, d.decision, d.decided_by, d.note AS decision_note, d.decided_at FROM invoices i {LATEST} "
                 f"WHERE i.invoice_id = :id AND ({w})", {**p, "id": invoice_id})
    if not rows:                                      # not found, or another customer's invoice: same answer
        raise HTTPException(404, f"Invoice '{invoice_id}' not found")
    return rows[0]


@router.get("/api/analysis/invoices/{invoice_id}")
def invoice(invoice_id: str, v: Viewer = Depends(who_is_asking)):
    inv = _one_invoice(invoice_id, v)
    inv["lines"] = _rows("SELECT line_no, line_type, compactor_id, service_date, quantity, unit, unit_price_eur, amount_eur, "
                         "check_status, expected_eur, difference_eur, check_reason FROM invoice_lines WHERE invoice_id = :id "
                         "ORDER BY line_no", {"id": invoice_id})
    inv["history"] = _rows("SELECT decision, decided_by, role, note, decided_at FROM invoice_decisions "
                           "WHERE invoice_id = :id ORDER BY id DESC", {"id": invoice_id})
    return inv


@router.post("/api/analysis/invoices/{invoice_id}/check")
def recheck(invoice_id: str, v: Viewer = Depends(who_is_asking)):
    _one_invoice(invoice_id, v)
    with get_engine().begin() as conn:
        return invoice_check.check(conn, invoice_id)


@router.post("/api/analysis/invoices/{invoice_id}/decision")
def decide(invoice_id: str, body: InvoiceDecisionIn, v: Viewer = Depends(who_is_asking)):
    _one_invoice(invoice_id, v)                       # 404 if it is not this viewer's invoice
    row = {"invoice_id": invoice_id, "decision": body.decision, "decided_by": body.decided_by.strip(), "role": v.role,
           "note": body.note, "decided_at": datetime.now(timezone.utc)}
    with get_engine().begin() as conn:
        row["id"] = conn.execute(insert(invoice_decisions).values(**row)).inserted_primary_key[0]
    return row


@router.get("/invoices", include_in_schema=False)
def invoices_page():
    return FileResponse(PAGE, media_type="text/html")
