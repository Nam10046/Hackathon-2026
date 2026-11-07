"""Contract tests: if these fail, the parts no longer fit together. Uses a temporary SQLite DB."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db.reset_engine()
    from app.main import app
    with TestClient(app) as c:  # "with" runs startup -> init_db()
        yield c
    db.reset_engine()


T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def send(client, cid, w, fill=None, minutes=0):
    body = {"compactor_id": cid, "weight_kg": w, "fill_pct": fill, "ts": (T0 + timedelta(minutes=minutes)).isoformat()}
    r = client.post("/api/readings", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_seeded_compactors(client):
    ids = [c["compactor_id"] for c in client.get("/api/compactors").json()]
    assert ids == ["C1", "C2", "C3"]


def test_reading_updates_status_and_value(client):
    res = send(client, "C1", 800, fill=50)
    s = res["status"]
    assert s["weight_kg"] == 800
    assert s["value_eur"] == pytest.approx(64.0)  # 800 kg × 0.08 €/kg
    assert s["density_kg_m3"] == pytest.approx(200.0)  # 800 / (0.5 × 8 m3)
    assert client.get("/api/compactors/C1").json()["value_eur"] == pytest.approx(64.0)


def test_unknown_compactor_404(client):
    r = client.post("/api/readings", json={"compactor_id": "NOPE", "weight_kg": 1})
    assert r.status_code == 404


def test_sensor_fault_alert(client):
    res = send(client, "C1", 99999)
    assert res["alerts"][0]["type"] == "sensor_fault"


def test_contamination_alert(client):
    res = send(client, "C1", 1800, fill=40)  # 1800 / 3.2 m3 = 562 kg/m3 > 450
    assert any(a["type"] == "contamination" for a in res["alerts"])


def test_spike_and_forecast(client):
    for i in range(10):
        res = send(client, "C1", 100 + i * 20, minutes=i * 60)  # +20 kg per hour
    assert res["status"]["hours_to_full"] is not None
    res = send(client, "C1", 900, minutes=11 * 60)  # +620 kg jump
    assert any(a["type"] == "spike" for a in res["alerts"])


def test_emptied_alert(client):
    send(client, "C1", 1200, minutes=0)
    res = send(client, "C1", 10, minutes=60)
    assert any(a["type"] == "emptied" for a in res["alerts"])
    assert "emptied" in {a["type"] for a in client.get("/api/alerts?compactor_id=C1").json()}


def test_bulk_and_history(client):
    body = {"readings": [
        {"compactor_id": "C2", "weight_kg": 50 * i, "ts": (T0 + timedelta(hours=i)).isoformat()} for i in range(5)
    ]}
    assert client.post("/api/readings/bulk", json=body).json()["stored"] == 5
    hist = client.get("/api/compactors/C2/readings").json()
    assert [h["weight_kg"] for h in hist] == [0, 50, 100, 150, 200]


def test_api_key_required_when_set(client, monkeypatch):
    monkeypatch.setenv("INGEST_API_KEY", "secret123")
    body = {"compactor_id": "C1", "weight_kg": 100}
    assert client.post("/api/readings", json=body).status_code == 401
    assert client.post("/api/readings", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/readings", json=body, headers={"X-API-Key": "secret123"}).status_code == 200
    assert client.get("/api/compactors").status_code == 200  # reading stays open


def test_tigerdata_url_is_accepted():
    url = "postgres://tsdbadmin:pw@abc.tsdb.cloud.timescale.com:31234/tsdb?sslmode=require"
    assert db.normalize_url(url) == "postgresql+psycopg://tsdbadmin:pw@abc.tsdb.cloud.timescale.com:31234/tsdb?sslmode=require"
    assert db.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_cockpit_approval_flow(client):
    from sqlalchemy import text
    with db.get_engine().begin() as conn:
        conn.execute(text("CREATE TABLE cp_actions (action_id TEXT, case_id TEXT, action TEXT, contract_id TEXT, "
                          "device_id TEXT, customer_name TEXT, operator_name TEXT, notice_period_days INTEGER, "
                          "flagged_invoice_eur REAL, rationale TEXT)"))
        conn.execute(text("INSERT INTO cp_actions VALUES ('OC-1-DISPUTE_INVOICE','OC-1','DISPUTE_INVOICE','CTR-1',"
                          "'CMP-1','Shop Oy','Hauler Alpha',30,120.5,'why')"))
        conn.execute(text("CREATE TABLE cp_flags (entity_type TEXT, entity_id TEXT, label_family TEXT, found_at TEXT, "
                          "device_id TEXT, explanation TEXT, evidence TEXT, eur_at_stake REAL, evidence_tag TEXT)"))
    assert client.get("/api/cockpit/actions").json()[0]["status"] == "PENDING"
    r = client.post("/api/cockpit/actions/OC-1-DISPUTE_INVOICE/decision", json={"decision": "APPROVE", "decided_by": "Nam"})
    assert r.json()["status"] == "APPROVED"
    assert client.get("/api/cockpit/actions?status=approved").json()[0]["decided_by"] == "Nam"
    client.post("/api/cockpit/actions/OC-1-DISPUTE_INVOICE/decision", json={"decision": "REVERT", "decided_by": "Nam"})
    ev = client.get("/api/cockpit/actions/OC-1-DISPUTE_INVOICE/evidence").json()
    assert [h["decision"] for h in ev["decision_history"]] == ["APPROVE", "REVERT"]
    assert client.get("/api/cockpit/actions").json()[0]["status"] == "PENDING"
    assert client.post("/api/cockpit/actions/NOPE/decision", json={"decision": "APPROVE", "decided_by": "x"}).status_code == 404
    assert "Customer Value Cockpit" in client.get("/cockpit").text


# ---- bad-data rules found with the simulator (simulator/simulate.py) ----
def types(res):
    return {a["type"] for a in res["alerts"]}


def test_noise_is_not_an_alarm(client):
    # +-40 kg wobble on a near-empty container is sensor noise, not a drop, spike or emptying
    for i, w in enumerate([60, 100, 55, 95, 45, 90, 50, 85]):
        assert not types(send(client, "C1", w, 5, minutes=60 * i)) & {"unexpected_drop", "spike", "emptied", "sensor_fault"}
    assert "sensor_fault" not in types(send(client, "C1", -30, 0, minutes=600))      # slightly negative = noise


def test_stuck_sensor_and_data_gap(client):
    for i in range(5):
        send(client, "C1", 800 + 20 * i, 40 + i, minutes=60 * i)
    got = [types(send(client, "C1", 900, 45, minutes=60 * (5 + i))) for i in range(6)]
    assert "sensor_stuck" in got[5] and not any("sensor_stuck" in g for g in got[:5])   # said once, at 6 in a row
    assert "data_gap" in types(send(client, "C1", 950, 47, minutes=60 * 11 + 60 * 6))   # 6 h silent


def test_zero_shift_after_emptying(client):
    for i in range(4):
        send(client, "C1", 1200 + 50 * i, 60 + 2 * i, minutes=60 * i)
    t = types(send(client, "C1", 230, 2, minutes=300))                                  # emptied, but reads 230 kg
    assert {"emptied", "zero_shift"} <= t


def test_duplicate_message_is_stored_once(client):
    first = send(client, "C1", 500, 25, minutes=0)
    again = send(client, "C1", 500, 25, minutes=0)
    assert again["duplicate"] and again["reading_id"] == first["reading_id"] and again["alerts"] == []


def test_overload(client):
    send(client, "C1", 1900, 90, minutes=0)
    assert "overload" in types(send(client, "C1", 2200, 92, minutes=60))                # C1 rated 2000 kg


# ---- edge node (firmware/edge_node): signed readings and the offline buffer ----
def _sign(key, cid, seq, epoch, w, f):
    import hashlib
    import hmac
    return hmac.new(key.encode(), f"{cid}|{seq}|{epoch}|{w:.1f}|{f:.1f}".encode(), hashlib.sha256).hexdigest()


def test_signed_reading_verified_and_tampered(client, monkeypatch):
    from sqlalchemy import select
    monkeypatch.setenv("DEVICE_KEYS", "C1:test-key")
    ts = T0 + timedelta(minutes=5)
    good = {"compactor_id": "C1", "weight_kg": 523.4, "fill_pct": 26.1, "ts": ts.isoformat(), "seq": 100001,
            "sig": _sign("test-key", "C1", 100001, int(ts.timestamp()), 523.4, 26.1)}
    r = client.post("/api/readings", json=good).json()
    assert "signature_invalid" not in {a["type"] for a in r["alerts"]}
    bad = {**good, "weight_kg": 623.4, "ts": (ts + timedelta(minutes=1)).isoformat()}   # weight changed afterwards
    assert "signature_invalid" in {a["type"] for a in client.post("/api/readings", json=bad).json()["alerts"]}
    with db.get_engine().connect() as conn:
        assert [v for (v,) in conn.execute(select(db.readings.c.verified).order_by(db.readings.c.id))] == [True, False]


def test_buffered_reading_is_marked(client):
    body = {"compactor_id": "C2", "weight_kg": 300, "fill_pct": 20, "ts": (T0 - timedelta(hours=2)).isoformat(),
            "edge": {"from_buffer": True, "quality": "OK", "spikes_filtered": 3}}
    assert "edge_buffered" in {a["type"] for a in client.post("/api/readings", json=body).json()["alerts"]}


def test_edge_fields_are_stored(client):
    from sqlalchemy import select
    from app.db import get_engine, readings
    body = {"compactor_id": "C1", "weight_kg": 412.0, "fill_pct": 20.0, "seq": 300007,
            "edge": {"quality": "stable", "spikes_filtered": 2, "from_buffer": False}}
    assert client.post("/api/readings", json=body).status_code == 200
    with get_engine().connect() as c:
        r = c.execute(select(readings).where(readings.c.seq == 300007)).mappings().first()
    assert (r["seq"], r["edge_quality"], r["spikes_filtered"], r["from_buffer"]) == (300007, "stable", 2, False)


def _feed(client, cid, kgs, start, step_s=10):
    out = []
    for i, w in enumerate(kgs):
        ts = (start + timedelta(seconds=i * step_s)).isoformat()
        out.append(client.post("/api/readings", json={"compactor_id": cid, "weight_kg": w, "fill_pct": w / 20, "ts": ts}).json())
    return out


def test_pickup_loop_book_truck_judge_invoice(client, monkeypatch):
    """C1 (2000 kg, on-call 80 %) fills up -> truck booked -> command to the board -> emptied -> judged + priced."""
    import random
    from app import pickups
    monkeypatch.setattr(pickups, "SCALE", 60.0)          # 1 min = 1 site hour
    monkeypatch.setattr(pickups, "P_TRUCK_LATE", 0.0)
    monkeypatch.setattr(pickups, "P_FIXED_ROUTE", 0.0)
    monkeypatch.setattr(pickups, "P_INVOICE_KG", 1.0)    # force a wrong invoice
    monkeypatch.setattr(pickups, "P_INVOICE_FEE", 0.0)
    random.seed(1)
    start = datetime.now(timezone.utc) - timedelta(minutes=30)
    kgs = [1000 + 30 * i for i in range(25)] + [1720 + (i % 4) * 3 for i in range(40)]   # crosses 1600, then waits 6.7 site h
    res = _feed(client, "C1", kgs, start)
    booked = [a for r in res for a in r["alerts"] if a["type"] == "pickup_booked"]
    assert len(booked) == 1
    cmds = [c for r in res for c in r.get("commands", [])]
    assert cmds and cmds[0]["compactor_id"] == "C1" and cmds[0]["action"] == "empty"   # truck due within 1.5-3.5 site h
    last = start + timedelta(seconds=len(kgs) * 10)
    r = _feed(client, "C1", [12], last)[0]                                         # the board reports it emptied
    types = {a["type"] for a in r["alerts"]}
    assert "pickup_on_time" in types and "invoice_mismatch" in types
    p = client.get("/api/pickups").json()[0]
    assert p["status"] == "done" and p["verdict"] == "ON_TIME" and p["kind"] == "booked"
    assert p["kg_collected"] > 1600 and p["invoice_check"] == "WEIGHT_MISMATCH" and p["claim_eur"] > 0
    assert p["net_eur"] == round(p["value_eur"] - p["fee_eur"], 2)


def test_early_lift_is_judged_too_early(client):
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    _feed(client, "C2", [600, 610, 620], start)                                   # 40 % of 1500 kg
    r = _feed(client, "C2", [10], start + timedelta(seconds=30))[0]
    assert "pickup_too_early" in {a["type"] for a in r["alerts"]}
