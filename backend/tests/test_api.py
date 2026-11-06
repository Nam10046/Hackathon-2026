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
