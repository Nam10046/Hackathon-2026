# Models folder

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
