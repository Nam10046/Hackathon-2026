"""Plug-in ML models. Owner: AI person.

Every folder in MODELS_DIR that has model.json + model.onnx is loaded at startup
(or with POST /api/models/reload). Same idea as the AIsmell inference service:
train -> export ONNX -> drop the folder in models/ -> the backend uses it. No code change.

model.json example:
  {"type": "anomaly", "input_features": ["weight_frac", ...], "description": "..."}

type "anomaly": model returns label (1 normal, -1 unusual) and a score, e.g. IsolationForest.
"""
import json
import os
from pathlib import Path

import numpy as np

_models: dict[str, dict] = {}


def models_dir() -> Path:
    return Path(os.getenv("MODELS_DIR", "./models"))


def load_all() -> list[str]:
    _models.clear()
    root = models_dir()
    if not root.exists():
        return []
    import onnxruntime as ort  # imported here so the app still starts if it's missing
    for meta_path in sorted(root.glob("*/model.json")):
        name = meta_path.parent.name
        try:
            meta = json.loads(meta_path.read_text())
            onnx_path = meta_path.parent / meta.get("file", "model.onnx")
            _models[name] = {"session": ort.InferenceSession(str(onnx_path)), "meta": meta}
            print(f"Loaded model: {name}", flush=True)
        except Exception as e:  # one broken model must not stop the server
            print(f"Warning: failed to load model {name}: {e}", flush=True)
    return list(_models)


def list_models() -> list[dict]:
    return [{"name": n, **m["meta"]} for n, m in _models.items()]


def check(features: dict) -> list[dict]:
    """Run every anomaly model on one reading's features. Returns alerts."""
    alerts = []
    for name, m in _models.items():
        meta = m["meta"]
        if meta.get("type") != "anomaly":
            continue
        try:
            x = np.array([[features[f] for f in meta["input_features"]]], dtype=np.float32)
            sess = m["session"]
            outs = sess.run(None, {sess.get_inputs()[0].name: x})
            label = int(np.asarray(outs[0]).ravel()[0])
            score = float(np.asarray(outs[1]).ravel()[0]) if len(outs) > 1 else 0.0
        except Exception as e:
            print(f"Warning: model {name} failed: {e}", flush=True)
            continue
        if label == -1:
            alerts.append({"type": "ml_anomaly", "severity": "warning",
                           "message": f"Model '{name}' flags this reading as unusual (score {score:.2f})"})
    return alerts
