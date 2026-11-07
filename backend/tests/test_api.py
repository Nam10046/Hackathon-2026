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
    assert client.get("/api/alerts?compactor_id=C1").json()[0]["type"] == "emptied"


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
