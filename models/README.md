# Models folder

## Included: the LIVE LIFT MODEL (trained on the Europress dataset)
| Folder | Answers at the moment of an emptying | Validation F1 (organisers' scorer) |
|---|---|---|
| `lift_premature/` | was this lift unnecessary (too early, no reason)? | **0.927** (rule baseline B2: 0.716 · ML baseline B4: 0.925) |
| `lift_delayed/` | did the lift come too late (overflow risk)? | **0.922** (B2: 0.773 · B4: 0.919) |
| `lift_premature_esp32/` | same, trained on the **ESP32 feed** (weight + fill + clock + the order-level setting) — used live | **0.778** |
| `lift_delayed_esp32/` | same, ESP32 feed — used live | **0.637** |

The cockpit (dataset, full SMART feed) uses the first two. The backend's live path sends `"feed": "esp32"` and
uses the `_esp32` pair (`model.json` → `"feed"`). Why two pairs: the full model given ESP32-only inputs drops to
F1 0.61 / 0.31 — see `python training/evaluate_lift_model.py` and `submission/06_model_accuracy_and_live_data.md`.

Inputs = only what the compactor knows live (`backend/app/ai/lift_features.py`), unlike B4 which also needs the
weighbridge weight and the cost per tonne — so ours can warn **before** the bill. Retrain:
`pip install -r training/requirements.txt` then `python training/train_lift_model.py` and
`python training/train_lift_model.py --feed esp32` (≈1 min each). Check accuracy: `python training/evaluate_lift_model.py`;
check the live path end to end: `python training/replay_live.py --devices 40`.

## Folder format

Every sub-folder with `model.json` + `model.onnx` is loaded by the backend.

```
models/
  anomaly_iforest/
    model.onnx     the trained model
    model.json     {"type": "anomaly", "input_features": [...], ...}
```

- Make one: `python training/train_anomaly.py` (needs collected readings in Postgres)
- Use it without restart: `POST http://localhost:8000/api/models/reload`
- See loaded models: `GET http://localhost:8000/api/models`
- Features are defined in `backend/app/ai/features.py` — change them → retrain.
- Small models (< a few MB) can be committed. Big ones → share via Drive.
