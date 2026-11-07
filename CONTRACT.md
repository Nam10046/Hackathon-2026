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
| PUT | `/materials/{name}` | `{"lift_fee_eur", "price_eur_per_t"}` — live estimate: cost per lift and price per tonne (+ they pay you, − you pay them), typed in by the customer (API key). Form: `GET /prices` |
| GET | `/models` | Loaded ML models (from `models/`) |
| POST | `/models/reload` | Load new/changed model folders without restart |
| GET | `/models/performance?days=30` | Live check per lift model: alerts per lift vs. the validation rate (drift), live precision from feedback |
| GET | `/pickups?limit=100` | Every lift: booked / done, verdict, kg, money, CO2, invoice check |
| GET | `/pickups/board` | Per compactor: `load_pct`, `on_call_pct`, `needs_truck`, open `truck` (for the booking panel) |
| POST | `/pickups/book` | `{"compactor_id": "C1"}` — a **person** books a truck (API key). 409 if one is already booked. Page with buttons: `GET /book` (not under `/api`) |
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
Alert `type` values: `sensor_fault`, `spike`, `unexpected_drop`, `contamination`, `emptied`, `nearly_full`, `ml_anomaly` (from a model in `models/`), `ml_premature_unjustified` and `ml_delayed_collection` (live lift model, checked on every emptying), and the bad-data checks found with the simulator: `sensor_stuck` (6 identical readings), `data_gap` (no reading for 3 intervals; env `READING_INTERVAL_H`, default 1), `zero_shift` (an emptied container does not read ~0), `overload` (above the rated payload); pickups: `pickup_needed` (on-call level reached, once per fill cycle — the system never books by itself), `pickup_booked`, `truck_arrived`, `pickup_on_time` / `pickup_too_early` / `pickup_too_late`, `invoice_mismatch`.

Sending the same reading twice (same compactor and `ts`) is safe: it is stored once and the answer has `"duplicate": true`.
An edge node (`firmware/edge_node`) may add `seq`, `sig` (HMAC-SHA256 hex of `id|seq|epoch|weight(.1f)|fill(.1f)`, `-` for a missing time) and an `edge` object (`quality`, `spikes_filtered`, `emptied`, `from_buffer`). With `DEVICE_KEYS=C1:key` set, the backend stores `readings.verified` and raises `signature_invalid` (critical) on a mismatch; `edge.from_buffer` raises `edge_buffered` (info).

Each compactor can carry the SMART setting `on_call_threshold_pct` (fill % that raises `pickup_needed`; a person then books); the live lift model uses it.
`severity`: `info`, `warning`, `critical`.

### Analysis API (our customers' live data) — for the user platform and Grafana
The ESP32 site is the demo customer (`DEMO_CUSTOMER`, default "Demo Customer (site S1)"). The Europress dataset is only used to
train the models. Admin sees all customers; a customer sees **only their own** rows. Until the user platform (teammate) is
merged, it says who is asking with headers it sets **after its own login check** (never from the browser):
`X-User-Role: admin|customer`, `X-Customer: <customer_name>`; admins also send `X-API-Key: <ADMIN_API_KEY>` when that is set
on the server. Someone else's invoice answers 404.

| Method | Path | What it does |
|---|---|---|
| GET | `/analysis/summary` | lifts, kg, verdict counts, problems, estimated cost (and per t), invoices, `waiting`, `to_check`, `overcharged_eur`, `unverified_eur`, `billed_eur` |
| GET | `/analysis/customers`, `/analysis/operators` | names this viewer may see |
| GET | `/analysis/problems?limit=100` | problem alerts from the board / backend, newest first |
| GET | `/analysis/pickups?limit=200` | measured lifts with the live cost estimate |
| GET | `/analysis/invoices?status=waiting&customer=` | `waiting` \| `approved` \| `rejected` \| `hold` \| `all`; `customer` filter for admins |
| GET | `/analysis/invoices/draft?operator=&period_from=&period_to=` | the invoice the measurement says you should get (lines) |
| POST | `/analysis/invoices` | type in an invoice: `{invoice_id, operator_name, period_from, period_to, total_eur, entered_by, lines: [{line_type, compactor_id, service_date, quantity, unit, unit_price_eur, amount_eur}]}` (API key) — stored and **checked at once**; 409 if the number exists |
| GET | `/analysis/invoices/{id}` | invoice + checked `lines` + decision `history` |
| POST | `/analysis/invoices/{id}/check` | check again (new pickups / prices) |
| POST | `/analysis/invoices/{id}/decision` | `{"decision": "APPROVE"\|"REJECT"\|"HOLD", "decided_by", "note"}` (API key). Page: `GET /invoices` |

**Invoice check** (`app/invoice_check.py`): `line_type` LIFT_FEE is matched to the board's emptyings (that day, or in the period)
→ `NO_LIFT` / `DUPLICATE`, and its unit price to the customer's cost per lift → `WRONG_PRICE`; PROCESSING / MATERIAL_CREDIT /
HAULAGE compare billed tonnes with measured tonnes (±4 %) → `WEIGHT_MISMATCH`, and the price per tonne → `WRONG_PRICE`;
SURCHARGE / PENALTY / OTHER → `NO_EVIDENCE` (ask for proof). `difference_eur` = amount − expected (+ = charged too much).
The invoice gets `suggestion` APPROVE \| CHECK; a person decides.

---

## 3. Database tables (PostgreSQL — Grafana reads these directly)

| Table | Columns |
|---|---|
| `materials` | `name` PK, `price_eur_per_kg`, `density_min`, `density_max`, `co2_factor`, `lift_fee_eur` |
| `compactors` | `id` PK, `name`, `material`, `capacity_kg`, `volume_m3`, `on_call_threshold_pct`, `customer_name`, `operator_name` |
| `readings` | `id`, `compactor_id`, `ts`, `weight_kg`, `fill_pct` |
| `alerts` | `id`, `compactor_id`, `ts`, `type`, `severity`, `message` |
| `compactor_status` | one row per compactor = the status object above |
| `invoices` | `invoice_id` PK, `customer_name`, `operator_name`, `period_from`, `period_to`, `total_eur`, `entered_by`, `entered_at`, `checked_at`, `suggestion`, `overcharged_eur`, `unverified_eur`, `lines_ok`, `lines_total`, `summary` |
| `invoice_lines` | `id`, `invoice_id`, `line_no`, `line_type`, `compactor_id`, `service_date`, `quantity`, `unit`, `unit_price_eur`, `amount_eur`, `check_status`, `expected_eur`, `difference_eur`, `check_reason` |
| `invoice_decisions` | `id`, `invoice_id`, `decision` (APPROVE \| REJECT \| HOLD), `decided_by`, `role`, `note`, `decided_at` — never updated, newest row counts |

Live money (Money & CO₂ page, `pickups.costs`) is a quick estimate: total cost = cost per lift − kg × price per tonne.
Invoices typed in on the Analysis page are checked line by line against the measured lifts and tonnes (see the Analysis API above).

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
| 2026-11-07 | Analysis on live data: the ESP32 site is a customer (`compactors.customer_name`, `operator_name`); invoices typed in and checked against the measurement (`invoices`, `invoice_lines`, `/analysis/*`, customer-scoped); invoice decisions | — |
| 2026-11-07 | Live prices: `PUT /materials/{name}` (cost per lift, price per tonne), `materials.lift_fee_eur`; material plastic → biowaste | — |
| 2026-11-07 | Manual truck booking: `/pickups/board`, `/pickups/book`, `pickup_needed` alert (no automatic booking) | — |
