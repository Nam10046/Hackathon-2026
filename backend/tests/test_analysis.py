"""Analysis on live data: an invoice typed in by the customer is checked against what the board measured; a person decides.
Real logins (app/auth.py): admin sees everything, a customer only the compactors assigned to their tenant, and forged
X-User-Role / X-Customer headers change nothing."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app import db, grafana
from tests.test_tenancy import ADMIN, FakeGrafana, sign_in

PERIOD = {"period_from": "2026-11-01", "period_to": "2026-11-30"}
A, B = "Customer A", "Customer B"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN[1])
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "strong-grafana-pass")
    monkeypatch.setenv("INGEST_API_KEY", "machine-key")
    fake = FakeGrafana()
    monkeypatch.setattr(grafana, "client", lambda: fake)
    db.reset_engine()
    from app.main import app
    with TestClient(app) as c:
        admin = sign_in(c, ADMIN[0], ADMIN[1])
        assert c.post("/api/admin/devices", headers=admin, json={"id": "C9", "name": "Other bin", "material": "mixed",
                                                                 "capacity_kg": 4000, "volume_m3": 8}).status_code == 201
        for email, company, devices in (("a@a.example", A, ["C1", "C2", "C3"]), ("b@b.example", B, ["C9"])):
            c.post("/api/auth/register", json={"email": email, "password": "correct-horse-battery", "company": company})
            uid = next(u["id"] for u in c.get("/api/admin/registrations", headers=admin).json() if u["email"] == email)
            r = c.post(f"/api/admin/registrations/{uid}/approve", headers=admin, json={"new_tenant_name": company, "device_ids": devices})
            assert r.status_code == 200, r.text
        with db.get_engine().begin() as conn:
            conn.execute(db.compactors.update().where(db.compactors.c.id == "C9").values(operator_name="Hauler Alpha"))
            # what the boards measured: A's C1 (cardboard, Hauler Alpha) on 3 and 4 Nov, C3 (mixed) on 4 Nov; B's C9
            for cid, day, kg in [("C1", 3, 1500), ("C1", 4, 1700), ("C3", 4, 3000), ("C9", 4, 2000)]:
                t = datetime(2026, 11, day, 12, tzinfo=timezone.utc)
                conn.execute(insert(db.pickups).values(compactor_id=cid, status="done", kind="booked", created_at=t, done_at=t,
                                                       kg_collected=kg, load_before_pct=85, verdict="ON_TIME", fee_eur=45))
        yield c, admin, sign_in(c, "a@a.example", "correct-horse-battery"), sign_in(c, "b@b.example", "correct-horse-battery")
    db.reset_engine()


def enter(c, h, lines, total=None, invoice_id="INV-1", operator="Hauler Alpha", **extra):
    body = {"invoice_id": invoice_id, "operator_name": operator, **PERIOD, "entered_by": "Nam", "lines": lines, **extra,
            "total_eur": round(sum(l["amount_eur"] for l in lines), 2) if total is None else total}
    return c.post("/api/analysis/invoices", json=body, headers=h)


LIFT = {"line_type": "LIFT_FEE", "compactor_id": "C1", "service_date": "2026-11-03", "quantity": 1, "unit": "lift",
        "unit_price_eur": 45, "amount_eur": 45}


def test_everything_needs_a_login(world):
    c, *_ = world
    for path in ("/api/analysis/summary", "/api/analysis/invoices", "/api/analysis/pickups", "/api/pickups/board"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/pickups/book", json={"compactor_id": "C1"}).status_code == 401
    assert enter(c, {}, [LIFT]).status_code == 401


def test_correct_invoice_is_suggested_for_approval(world):
    """The draft = the invoice the measurement says you should get: it checks clean."""
    c, _, a, _ = world
    draft = c.get("/api/analysis/invoices/draft", params={"operator": "Hauler Alpha", **PERIOD}, headers=a).json()
    assert [l["line_type"] for l in draft].count("LIFT_FEE") == 3          # C1 x2 + C3; B's C9 is not in A's draft
    r = enter(c, a, draft)
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"] == "APPROVE" and r.json()["overcharged_eur"] == 0
    assert {l["check_status"] for l in c.get("/api/analysis/invoices/INV-1", headers=a).json()["lines"]} == {"OK"}


def test_check_finds_what_the_board_disproves(world):
    c, _, a, _ = world
    lines = [
        LIFT,
        {**LIFT},                                                                                             # twice
        {**LIFT, "service_date": "2026-11-04", "unit_price_eur": 55, "amount_eur": 55},                        # old price
        {**LIFT, "compactor_id": "C3", "service_date": "2026-11-10", "unit_price_eur": 85, "amount_eur": 85},  # no lift that day
        {"line_type": "MATERIAL_CREDIT", "compactor_id": "C1", "quantity": 2.8, "unit": "t", "unit_price_eur": 80, "amount_eur": -224},  # measured 3.2 t
        {"line_type": "SURCHARGE", "quantity": 1, "unit": "pcs", "unit_price_eur": 30, "amount_eur": 30},     # fuel surcharge
    ]
    res = enter(c, a, lines, total=40).json()                      # printed total differs from the lines (36)
    assert res["suggestion"] == "CHECK" and res["lines_ok"] == 1 and res["lines_total"] == 6
    out = c.get("/api/analysis/invoices/INV-1", headers=a).json()["lines"]
    assert [l["check_status"] for l in out] == ["OK", "DUPLICATE", "WRONG_PRICE", "NO_LIFT", "WEIGHT_MISMATCH", "NO_EVIDENCE"]
    assert [out[i]["difference_eur"] for i in (1, 2, 3, 4)] == [45, 10, 85, 32] and out[4]["expected_eur"] == -256
    assert res["overcharged_eur"] == 176 and res["unverified_eur"] == 30 and "lines add up to 36.00" in res["summary"]
    assert enter(c, a, lines).status_code == 409                   # same invoice number again


def test_customer_sees_only_own_data_even_with_forged_headers(world):
    c, admin, a, b = world
    assert enter(c, a, [LIFT]).status_code == 200
    r = enter(c, b, [{**LIFT, "compactor_id": "C9", "service_date": "2026-11-04", "unit_price_eur": 85, "amount_eur": 85}], invoice_id="INV-B")
    assert r.status_code == 200 and r.json()["suggestion"] == "APPROVE"
    forged = {**a, "X-User-Role": "admin", "X-Customer": B}       # A pretends to be admin / customer B: ignored
    assert {i["invoice_id"] for i in c.get("/api/analysis/invoices?status=all", headers=forged).json()} == {"INV-1"}
    assert {i["invoice_id"] for i in c.get(f"/api/analysis/invoices?status=all&customer={B}", headers=forged).json()} == {"INV-1"}
    assert c.get("/api/analysis/invoices/INV-B", headers=forged).status_code == 404
    assert c.post("/api/analysis/invoices/INV-B/decision", headers=forged, json={"decision": "APPROVE", "decided_by": "Me"}).status_code == 404
    assert {p["compactor_id"] for p in c.get("/api/analysis/pickups", headers=forged).json()} == {"C1", "C3"}
    assert [x["compactor_id"] for x in c.get("/api/pickups/board", headers=forged).json()] == ["C1", "C2", "C3"]
    assert c.post("/api/pickups/book", headers=forged, json={"compactor_id": "C9"}).status_code == 404   # B's compactor
    assert c.get("/api/analysis/summary", headers=forged).json()["lifts"] == 3
    assert c.get("/api/analysis/customers", headers=forged).json() == [A]
    # a customer cannot bill against someone else's compactor
    enter(c, a, [{**LIFT, "compactor_id": "C9", "service_date": None}], invoice_id="INV-X")
    assert c.get("/api/analysis/invoices/INV-X", headers=a).json()["lines"][0]["check_status"] == "UNKNOWN_COMPACTOR"
    # the admin sees both customers
    assert {i["invoice_id"] for i in c.get("/api/analysis/invoices?status=all", headers=admin).json()} == {"INV-1", "INV-B", "INV-X"}
    assert c.get("/api/analysis/summary", headers=admin).json()["lifts"] == 4


def test_decisions_are_kept_and_signed(world):
    c, admin, a, _ = world
    enter(c, a, [LIFT])
    assert c.post("/api/analysis/invoices/INV-1/decision", headers=admin, json={"decision": "HOLD", "decided_by": "Nam"}).status_code == 200
    r = c.post("/api/analysis/invoices/INV-1/decision", headers=a, json={"decision": "APPROVE", "decided_by": "Anna", "note": "ok"})
    assert r.status_code == 200 and r.json()["role"] == "customer"
    inv = c.get("/api/analysis/invoices/INV-1", headers=a).json()
    assert inv["decision"] == "APPROVE" and [h["decision"] for h in inv["history"]] == ["APPROVE", "HOLD"]
    assert "INV-1" not in {i["invoice_id"] for i in c.get("/api/analysis/invoices?status=waiting", headers=a).json()}
    assert c.post("/api/analysis/invoices/INV-1/decision", headers=a, json={"decision": "MAYBE", "decided_by": "Nam"}).status_code == 422
    assert c.post("/api/analysis/invoices/INV-1/check", headers=a).json()["suggestion"] == "APPROVE"
    bad = {"invoice_id": "I", "operator_name": "H", "period_from": "2026-11-05", "period_to": "2026-11-01", "total_eur": 1,
           "entered_by": "Nam", "lines": [{"line_type": "OTHER", "amount_eur": 1}]}
    assert c.post("/api/analysis/invoices", json=bad, headers=a).status_code == 422          # period backwards
    assert "Enter an invoice" in c.get("/invoices").text


def test_only_an_admin_changes_prices(world):
    c, admin, a, _ = world
    assert c.put("/api/materials/cardboard", headers=a, json={"lift_fee_eur": 1, "price_eur_per_t": 1}).status_code == 403
    assert c.put("/api/materials/cardboard", headers=admin, json={"lift_fee_eur": 50, "price_eur_per_t": 90}).status_code == 200


def test_issues_are_counted_once(world):
    """One issue per badly timed lift; the same device fault on the same compactor in one hour counts once."""
    c, _, a, b = world
    t = datetime(2026, 11, 5, 12, 10, tzinfo=timezone.utc)
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.pickups).values(compactor_id="C1", status="done", kind="booked", created_at=t, done_at=t,
                                               kg_collected=500, load_before_pct=30, verdict="TOO_EARLY", verdict_reason="at 30%"))
        for minute in (12, 20, 40):                      # 3 gaps within one hour -> 1 issue
            conn.execute(insert(db.alerts).values(compactor_id="C2", ts=t.replace(minute=minute), type="data_gap",
                                                  severity="warning", message="No data for 2 min"))
        conn.execute(insert(db.alerts).values(compactor_id="C1", ts=t, type="ml_delayed_collection", severity="info",
                                              message="AI second opinion"))            # not an issue
    s = c.get("/api/analysis/summary", headers=a).json()
    assert (s["issues"], s["lift_issues"], s["device_issues"]) == (2, 1, 1)
    assert sorted((x["kind"], x["times"]) for x in c.get("/api/analysis/problems", headers=a).json()) == [("device", 3), ("lift", 1)]
    assert c.get("/api/analysis/problems", headers=b).json() == []


def test_book_works_with_only_a_grafana_login(world, monkeypatch):
    """The Book truck panel lives inside Grafana: a Grafana login in the admin org is enough, no Portal sign-in.
    A Grafana login in a customer's org, or a fake cookie, is not."""
    from app import access
    c, *_ = world
    c.cookies.clear()
    users = {"admin-session": {"login": "admin", "orgId": 1}, "customer-session": {"login": "a@a.example", "orgId": 7}}
    monkeypatch.setattr(access, "_grafana_user", lambda s: users.get(s))
    access._seen.clear()
    assert c.get("/api/pickups/board").status_code == 401                                   # nobody signed in
    for cookie, status in (("admin-session", 200), ("customer-session", 401), ("made-up", 401)):
        c.cookies.set("grafana_session", cookie)
        assert c.get("/api/pickups/board").status_code == status, cookie
        assert c.post("/api/pickups/book", json={"compactor_id": "C1"}).status_code == status, cookie
    c.cookies.clear()
    c.cookies.set("grafana_session", "admin-session")
    assert c.get("/api/analysis/summary").status_code == 401           # only the booking panel accepts the Grafana login
    c.cookies.clear()
