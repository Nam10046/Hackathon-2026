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


def test_live_lift_model(tmp_path, monkeypatch):
    """A lift model in models/ judges every emptying, using only the compactor's own readings."""
    import json
    from datetime import datetime, timedelta, timezone

    from sklearn.ensemble import GradientBoostingClassifier
    from skl2onnx import to_onnx

    from app.ai.lift_features import FEATURES
    rng = np.random.default_rng(1)
    X = rng.uniform(-1, 100, (300, len(FEATURES))).astype(np.float32)
    y = (X[:, FEATURES.index("fill_before")] < 40).astype(int)          # toy rule: low fill = premature
    m = GradientBoostingClassifier(n_estimators=20).fit(X, y)
    out = tmp_path / "models" / "lift_premature"
    out.mkdir(parents=True)
    onx = to_onnx(m, X[:1], target_opset={"": 17, "ai.onnx.ml": 3}, options={id(m): {"zipmap": False}})
    (out / "model.onnx").write_bytes(onx.SerializeToString())
    (out / "model.json").write_text(json.dumps({"type": "lift_classifier", "family": "PREMATURE_UNJUSTIFIED",
                                                "input_features": FEATURES, "threshold": 0.5, "alert_message": "Too early"}))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'lift.db'}")
    db.reset_engine()
    from app.main import app
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with TestClient(app) as c:
        send = lambda w, fill, h: c.post("/api/readings", json={"compactor_id": "C1", "weight_kg": w, "fill_pct": fill,  # noqa: E731
                                                              "ts": (t0 + timedelta(hours=h)).isoformat()}).json()
        for i in range(5):
            send(100 + 50 * i, 5 + 5 * i, i)                             # fills up to 25 % only
        res = send(5, 0, 6)                                               # emptied at 25 % -> premature
        types = [a["type"] for a in res["alerts"]]
        assert "emptied" in types and "ml_premature_unjustified" in types

        # someone checks it on site: correct -> live precision; the performance page counts it
        alert_id = next(a["id"] for a in c.get("/api/alerts?compactor_id=C1").json() if a["type"] == "ml_premature_unjustified")
        assert c.post(f"/api/alerts/{alert_id}/feedback", json={"verdict": "CORRECT", "decided_by": "test"}).status_code == 200
        assert c.post("/api/alerts/999999/feedback", json={"verdict": "CORRECT", "decided_by": "test"}).status_code == 404
        perf = c.get("/api/models/performance").json()["models"][0]
        assert perf["alert_type"] == "ml_premature_unjustified" and perf["feedback_correct"] == 1 and perf["alerts"] == 1
        assert perf["status"].startswith("too early")                    # only 1 lift so far

        # a model trained on the ESP32 feed takes over from the full-feed model for live readings
        esp = tmp_path / "models" / "lift_premature_esp32"
        esp.mkdir()
        (esp / "model.onnx").write_bytes(onx.SerializeToString())
        (esp / "model.json").write_text(json.dumps({"type": "lift_classifier", "family": "PREMATURE_UNJUSTIFIED", "feed": "esp32",
                                                    "input_features": FEATURES, "threshold": 1.01, "alert_message": "x"}))
        c.post("/api/models/reload")
        for i in range(5):
            send(100 + 50 * i, 5 + 5 * i, 10 + i)
        types = [a["type"] for a in send(5, 0, 16)["alerts"]]
        assert "emptied" in types and "ml_premature_unjustified" not in types   # esp32 model (never fires) was used
    db.reset_engine()
