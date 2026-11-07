# Data Contract

The agreement between **hardware, Node-RED, backend, AI and dashboard**. Code against this file.
Changing it = a PR that edits this file + a message to the whole team.

## The big picture

```
ESP32 sensor ─────MQTT──► Mosquitto ──► Node-RED ──HTTP──► FastAPI backend ──► PostgreSQL ◄── Grafana
                                                             (AI: anomaly, forecast, value)
```

---

## 1. Sensor reading (the most important format)

Sent by the ESP32 (or a Node-RED test button) as **MQTT** message:

- **Topic:** `compactor/<compactor_id>/reading` — e.g. `compactor/C1/reading`
- **Payload (JSON):**
```json
{
  "compactor_id": "C1",
  "weight_kg": 812.4,
  "fill_pct": 47.5,
  "ts": "2026-11-06T15:30:00Z"
}
```
| Field | Type | Required | Notes |
|---|---|---|---|
| `compactor_id` | string | yes | Must exist in `compactors` table (C1, C2, C3 seeded) |
| `weight_kg` | number | yes | Net weight after tare. Can be slightly negative from noise |
| `fill_pct` | number 0–100 | no | From distance sensor / press position. Needed for density check |
| `ts` | ISO-8601 UTC | no | Server time is used if missing |

Node-RED forwards the same JSON to the backend.

---

## 2. Backend HTTP API (`http://localhost:8000/api`, docs at `/docs`)

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | `{"status":"ok","version":"..."}` |
| POST | `/readings` | Store one reading (body = format above), run AI checks. Returns `{"reading_id", "alerts":[...], "status":{...}}` |
| POST | `/readings/bulk` | `{"readings":[...]}` — many at once, in time order (import old data) |
| GET | `/compactors` | List of compactor status objects (below) |
| GET | `/compactors/{id}` | One status object |
| GET | `/compactors/{id}/readings?limit=500` | Latest readings, oldest first |
| GET | `/alerts?compactor_id=C1&limit=50` | Latest alerts, newest first |
| GET | `/materials` | Price & density table |
| GET | `/models` | Loaded ML models (from `models/`) |
| POST | `/models/reload` | Load new/changed model folders without restart |
| GET | `/models/performance?days=30` | Live check per lift model: alerts per lift vs. the validation rate (drift), live precision from feedback |
| POST | `/alerts/{id}/feedback` | `{"verdict": "CORRECT"\|"FALSE_ALARM", "decided_by", "note"}` — was this alert right? (API key) |

**Writes need a key:** if the server has `INGEST_API_KEY` set (always on Rahti), `POST` requests must send
header `X-API-Key: <key>`. Reading (GET) is open. On the laptop the key is empty = open.

**Status object**
```json
{
  "compactor_id": "C1",
  "name": "Warehouse cardboard",
  "material": "cardboard",
  "weight_kg": 812.4,
  "fill_pct": 47.5,
  "load_pct": 47.5,
  "density_kg_m3": 213.9,
  "value_eur": 64.99,
  "co2_saved_kg": 731.2,
  "hours_to_full": 31.5,
  "last_ts": "2026-11-06T15:30:00Z"
}
```
- `load_pct` = the bigger of `fill_pct` and `weight_kg / capacity_kg × 100`.
- `value_eur` positive = customer earns, negative = customer pays.
- `hours_to_full` = `null` if not enough data or not filling.

**Alert object**
```json
{ "id": 7, "compactor_id": "C1", "ts": "...", "type": "contamination",
  "severity": "warning", "message": "Density 520 kg/m³ is above normal for cardboard (150–450)" }
```
Alert `type` values: `sensor_fault`, `spike`, `unexpected_drop`, `contamination`, `emptied`, `nearly_full`, `ml_anomaly` (from a model in `models/`), `ml_premature_unjustified` and `ml_delayed_collection` (live lift model, checked on every emptying), and the bad-data checks found with the simulator: `sensor_stuck` (6 identical readings), `data_gap` (no reading for 3 intervals; env `READING_INTERVAL_H`, default 1), `zero_shift` (an emptied container does not read ~0), `overload` (above the rated payload).

Sending the same reading twice (same compactor and `ts`) is safe: it is stored once and the answer has `"duplicate": true`.
Each compactor can carry the SMART setting `on_call_threshold_pct` (fill % that orders a truck); the live lift model uses it.
`severity`: `info`, `warning`, `critical`.

---

## 3. Database tables (PostgreSQL — Grafana reads these directly)

| Table | Columns |
|---|---|
| `materials` | `name` PK, `price_eur_per_kg`, `density_min`, `density_max`, `co2_factor` |
| `compactors` | `id` PK, `name`, `material`, `capacity_kg`, `volume_m3` |
| `readings` | `id`, `compactor_id`, `ts`, `weight_kg`, `fill_pct` |
| `alerts` | `id`, `compactor_id`, `ts`, `type`, `severity`, `message` |
| `compactor_status` | one row per compactor = the status object above |

Only the backend **writes**. Grafana and others **read**.

## 4. ML model folder

`models/<name>/model.onnx` + `model.json` (`type`, `input_features`). Input features are defined in
`backend/app/ai/features.py` and shared with `training/train_anomaly.py`. Output for `type: anomaly`:
label (`1` normal, `-1` unusual) + score.

## Change log
| Date | Change | By |
|---|---|---|
| 2026-11-06 | Compactor contract v1 (MQTT reading, API, tables) | — |
| 2026-11-06 | ML model folder + `/models` endpoints, `ml_anomaly` alert | — |
