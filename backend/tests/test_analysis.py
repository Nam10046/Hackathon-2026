"""Analysis on live data: an invoice typed in by the customer is checked against what the board measured; a person decides.
Admin sees everything, a customer only their own rows."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app import db

CUST = db.DEMO_CUSTOMER
OTHER = "Other Customer"
ADMIN = {"X-User-Role": "admin"}
ME = {"X-User-Role": "customer", "X-Customer": CUST}
THEM = {"X-User-Role": "customer", "X-Customer": OTHER}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    db.reset_engine()
    from app.main import app
    with TestClient(app) as c:
        with db.get_engine().begin() as conn:
            conn.execute(insert(db.compactors).values(id="C9", name="Other bin", material="mixed", capacity_kg=4000,
                                                      volume_m3=8, customer_name=OTHER, operator_name="Hauler Alpha"))
            # what the board measured: C1 (cardboard, Hauler Alpha) emptied on 3 and 4 Nov, C3 (mixed) on 4 Nov, C9 (other customer)
            for cid, day, kg in [("C1", 3, 1500), ("C1", 4, 1700), ("C3", 4, 3000), ("C9", 4, 2000)]:
                t = datetime(2026, 11, day, 12, tzinfo=timezone.utc)
                conn.execute(insert(db.pickups).values(compactor_id=cid, status="done", kind="booked", created_at=t, done_at=t,
                                                       kg_collected=kg, load_before_pct=85, verdict="ON_TIME", fee_eur=45))
        yield c
    db.reset_engine()


PERIOD = {"period_from": "2026-11-01", "period_to": "2026-11-30"}


def enter(client, lines, total=None, invoice_id="INV-1", headers=None, operator="Hauler Alpha"):
    body = {"invoice_id": invoice_id, "operator_name": operator, **PERIOD, "entered_by": "Nam", "lines": lines,
            "total_eur": round(sum(l["amount_eur"] for l in lines), 2) if total is None else total}
    return client.post("/api/analysis/invoices", json=body, headers=headers or ADMIN)


def test_correct_invoice_is_suggested_for_approval(client):
    """The draft = the invoice the measurement says you should get: it checks clean."""
    draft = client.get("/api/analysis/invoices/draft", params={"operator": "Hauler Alpha", **PERIOD}).json()
    # 3 lifts (C1 x2, C3) at your cost per lift + credit for 3.2 t cardboard + processing for 3.0 t mixed waste
    assert [l["line_type"] for l in draft].count("LIFT_FEE") == 3
    r = enter(client, draft)
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"] == "APPROVE" and r.json()["overcharged_eur"] == 0
    inv = client.get("/api/analysis/invoices/INV-1").json()
    assert {l["check_status"] for l in inv["lines"]} == {"OK"}


def test_check_finds_what_the_board_disproves(client):
    lines = [
        {"line_type": "LIFT_FEE", "compactor_id": "C1", "service_date": "2026-11-03", "quantity": 1, "unit": "lift", "unit_price_eur": 45, "amount_eur": 45},
        {"line_type": "LIFT_FEE", "compactor_id": "C1", "service_date": "2026-11-03", "quantity": 1, "unit": "lift", "unit_price_eur": 45, "amount_eur": 45},   # twice
        {"line_type": "LIFT_FEE", "compactor_id": "C1", "service_date": "2026-11-04", "quantity": 1, "unit": "lift", "unit_price_eur": 55, "amount_eur": 55},   # old price
        {"line_type": "LIFT_FEE", "compactor_id": "C3", "service_date": "2026-11-10", "quantity": 1, "unit": "lift", "unit_price_eur": 85, "amount_eur": 85},   # no lift that day
        {"line_type": "MATERIAL_CREDIT", "compactor_id": "C1", "quantity": 2.8, "unit": "t", "unit_price_eur": 80, "amount_eur": -224},  # we measured 3.2 t
        {"line_type": "SURCHARGE", "quantity": 1, "unit": "pcs", "unit_price_eur": 30, "amount_eur": 30},                                   # fuel surcharge
    ]
    r = enter(client, lines, total=40)                 # printed total differs from the lines (36)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["suggestion"] == "CHECK" and res["lines_ok"] == 1 and res["lines_total"] == 6
    st = [l["check_status"] for l in client.get("/api/analysis/invoices/INV-1").json()["lines"]]
    assert st == ["OK", "DUPLICATE", "WRONG_PRICE", "NO_LIFT", "WEIGHT_MISMATCH", "NO_EVIDENCE"]
    lines_out = client.get("/api/analysis/invoices/INV-1").json()["lines"]
    assert lines_out[1]["difference_eur"] == 45 and lines_out[2]["difference_eur"] == 10 and lines_out[3]["difference_eur"] == 85
    assert lines_out[4]["expected_eur"] == -256 and lines_out[4]["difference_eur"] == 32      # 0.4 t credit missing x 80 €
    # overcharged = 45 + 10 + 85 + 32 + 4 (total printed higher than the lines); the surcharge needs proof
    assert res["overcharged_eur"] == 176 and res["unverified_eur"] == 30
    assert "lines add up to 36.00" in res["summary"]
    assert enter(client, lines).status_code == 409                                             # same invoice number again


def test_decide_and_customer_scope(client):
    enter(client, [{"line_type": "LIFT_FEE", "compactor_id": "C1", "service_date": "2026-11-03", "quantity": 1, "unit": "lift",
                    "unit_price_eur": 45, "amount_eur": 45}], headers=ME)
    r = enter(client, [{"line_type": "LIFT_FEE", "compactor_id": "C9", "service_date": "2026-11-04", "quantity": 1, "unit": "lift",
                        "unit_price_eur": 85, "amount_eur": 85}], invoice_id="INV-OTHER", headers=THEM)
    assert r.status_code == 200 and r.json()["suggestion"] == "APPROVE"
    # a customer cannot bill against someone else's compactor
    r = enter(client, [{"line_type": "LIFT_FEE", "compactor_id": "C9", "quantity": 1, "unit": "lift", "unit_price_eur": 85,
                        "amount_eur": 85}], invoice_id="INV-X", headers=ME)
    assert client.get("/api/analysis/invoices/INV-X", headers=ME).json()["lines"][0]["check_status"] == "UNKNOWN_COMPACTOR"
    assert {i["invoice_id"] for i in client.get("/api/analysis/invoices?status=all", headers=ME).json()} == {"INV-1", "INV-X"}
    assert {i["invoice_id"] for i in client.get("/api/analysis/invoices?status=all", headers=ADMIN).json()} == {"INV-1", "INV-X", "INV-OTHER"}
    assert client.get("/api/analysis/invoices/INV-OTHER", headers=ME).status_code == 404
    assert client.post("/api/analysis/invoices/INV-OTHER/decision", headers=ME, json={"decision": "APPROVE", "decided_by": "Me"}).status_code == 404
    assert [p["compactor_id"] for p in client.get("/api/analysis/pickups", headers=THEM).json()] == ["C9"]
    assert client.get("/api/analysis/summary", headers=ME).json()["lifts"] == 3
    assert client.get("/api/analysis/customers", headers=ME).json() == [CUST]

    assert client.post("/api/analysis/invoices/INV-1/decision", json={"decision": "HOLD", "decided_by": "Nam"}).status_code == 200
    r = client.post("/api/analysis/invoices/INV-1/decision", headers=ME, json={"decision": "APPROVE", "decided_by": "Anna", "note": "ok"})
    assert r.status_code == 200 and r.json()["role"] == "customer"
    inv = client.get("/api/analysis/invoices/INV-1").json()
    assert inv["decision"] == "APPROVE" and [h["decision"] for h in inv["history"]] == ["APPROVE", "HOLD"]
    assert "INV-1" not in {i["invoice_id"] for i in client.get("/api/analysis/invoices?status=waiting").json()}
    assert client.post("/api/analysis/invoices/INV-1/decision", json={"decision": "MAYBE", "decided_by": "Nam"}).status_code == 422
    assert client.post("/api/analysis/invoices/INV-1/check").json()["suggestion"] == "APPROVE"
    assert "Enter an invoice" in client.get("/invoices").text


def test_access_rules(client, monkeypatch):
    assert client.get("/api/analysis/summary", headers={"X-User-Role": "customer"}).status_code == 400   # no customer name
    assert client.get("/api/analysis/summary", headers={"X-User-Role": "boss"}).status_code == 400
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")                                                    # on a server
    assert client.get("/api/analysis/summary").status_code == 401
    assert client.get("/api/analysis/summary", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/analysis/summary", headers=ME).status_code == 200
    bad = {"invoice_id": "I", "operator_name": "H", "period_from": "2026-11-05", "period_to": "2026-11-01", "total_eur": 1,
           "entered_by": "Nam", "lines": [{"line_type": "OTHER", "amount_eur": 1}]}
    assert client.post("/api/analysis/invoices", json=bad, headers=ME).status_code == 422          # period backwards


def test_issues_are_counted_once(client):
    """One issue per badly timed lift; the same device fault on the same compactor in one hour counts once."""
    t = datetime(2026, 11, 5, 12, 10, tzinfo=timezone.utc)
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.pickups).values(compactor_id="C1", status="done", kind="booked", created_at=t, done_at=t,
                                               kg_collected=500, load_before_pct=30, verdict="TOO_EARLY", verdict_reason="at 30%"))
        for minute in (12, 20, 40):                      # 3 gaps within one hour -> 1 issue
            conn.execute(insert(db.alerts).values(compactor_id="C2", ts=t.replace(minute=minute), type="data_gap",
                                                  severity="warning", message="No data for 2 min"))
        conn.execute(insert(db.alerts).values(compactor_id="C1", ts=t, type="ml_delayed_collection", severity="info",
                                              message="AI second opinion"))            # not an issue
    s = client.get("/api/analysis/summary", headers=ME).json()
    assert (s["issues"], s["lift_issues"], s["device_issues"]) == (2, 1, 1)
    probs = client.get("/api/analysis/problems", headers=ME).json()
    assert sorted((x["kind"], x["times"]) for x in probs) == [("device", 3), ("lift", 1)]
    assert client.get("/api/analysis/problems", headers=THEM).json() == []
