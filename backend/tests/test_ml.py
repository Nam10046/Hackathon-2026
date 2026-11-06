"""Plug-in model test: train a tiny model, drop it in a temp models/ folder, check the API uses it."""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("skl2onnx")
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "training"))
from train_anomaly import train_and_export  # noqa: E402


def test_model_plugin(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    # "normal" data: slowly filling compactors, small increases, normal density
    w = rng.uniform(0, 0.9, 500)
    X = np.column_stack([w, rng.uniform(0, 0.02, 500), w * 0.9, rng.uniform(0.4, 0.9, 500)]).astype(np.float32)
    train_and_export(X, tmp_path / "models" / "test_iforest", contamination=0.01)

    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db.reset_engine()
    from app.main import app
    with TestClient(app) as c:
        assert [m["name"] for m in c.get("/api/models").json()] == ["test_iforest"]
        normal = c.post("/api/readings", json={"compactor_id": "C1", "weight_kg": 800, "fill_pct": 50}).json()
        assert not any(a["type"] == "ml_anomaly" for a in normal["alerts"])
        weird = c.post("/api/readings", json={"compactor_id": "C1", "weight_kg": 1900, "fill_pct": 21}).json()
        assert any(a["type"] == "ml_anomaly" for a in weird["alerts"])
        assert c.post("/api/models/reload").json()["loaded"] == ["test_iforest"]
    db.reset_engine()
