"""Contract tests: if these fail, the parts no longer fit together."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_predict_matches_contract():
    r = client.post("/api/predict", json={"text": "I love this"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"label", "score", "explanation", "model"}
    assert 0 <= body["score"] <= 1


def test_predict_rejects_empty_text():
    r = client.post("/api/predict", json={"text": ""})
    assert r.status_code == 422
