# Context for AI assistants (Claude, Copilot, ChatGPT…)

Give this file to the AI first, so its code fits the team's project.

## Project
Hackathon 2026, Europress Group challenge: measure waste weight at industrial compactors and turn it into
useful information — material value, anomaly detection, pickup planning, new services.
Team are beginners: prefer simple, readable code with short comments over clever code.

## Architecture
ESP32 sensor → MQTT (Mosquitto) → Node-RED → FastAPI backend → PostgreSQL ← Grafana

## Stack & files
- **Firmware:** PlatformIO project `firmware/compactor_node/` (ESP32, Arduino framework). Libraries in `platformio.ini`. Secrets in `include/config.h` (git-ignored).
- **Node-RED:** `nodered/flows.json`. MQTT topic `compactor/+/reading` → POST `http://backend:8000/api/readings`.
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 Core (no ORM classes), pytest.
  - `app/main.py` endpoints · `app/service.py` ingest logic · `app/db.py` tables + seed data · `app/schemas.py` shapes
  - Works with PostgreSQL (local Docker or TigerData cloud, SSL required) and SQLite (tests) — keep queries portable (use SQLAlchemy, not raw Postgres-only SQL).
- **AI:** `app/ai/anomaly.py` `check(new, history, compactor, material) -> list[alert]`, `forecast.py` `hours_to_full(points, load_pct)`, `value.py` `material_value(weight, material)`. Keep these signatures.
  - `app/ai/features.py` = features shared by live backend and training. `app/ai/ml.py` loads ONNX models from `models/`.
- **Training:** `training/train_anomaly.py` (scikit-learn IsolationForest → ONNX via skl2onnx) → `models/<name>/`.
- **Testing without sensor:** test buttons (inject nodes) in the Node-RED flow publish sample readings.
- **Dashboard:** Grafana, `grafana/dashboards/compactor.json`, reads PostgreSQL directly (read-only).
- **Run all:** `docker compose up -d --build`. Ports: Grafana 3000, Node-RED 1880, API 8000, Adminer 8080, Postgres 5432, MQTT 1883. Settings in `.env` (see `.env.example`).

- **Frontend:** `app/static/assets/` (no build step). Screens call only `SC.data`. See `docs/FRONTEND_HANDOFF_NAM.md`.
- **Customers:** `app/auth.py`, `app/tenants.py`, `app/provision.py`, `docs/MULTI_TENANT.md`. Customer SQL uses only `tenant_api.*`.

## Rules for generated code
1. Follow `CONTRACT.md` exactly — JSON fields, MQTT topic, endpoints, table columns.
2. Only touch files for the current task. Don't reformat other people's files.
3. No secrets in code. Use environment variables or git-ignored config files.
4. Any backend/AI change → add or update a test in `backend/tests/`, and `pytest` must pass.
5. New Python packages → add to the right `requirements.txt` with a pinned version.
6. Only the backend writes to the database. Grafana/Node-RED read or call the API.
