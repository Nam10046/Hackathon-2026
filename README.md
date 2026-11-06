# Smart Compactor — Hackathon 2026 (Europress Group challenge)

> **Pitch:** We tell companies what their waste weighs and is worth **before the truck leaves** — and warn them when something is wrong.

## The server framework

```
 ESP32 + load cell ──MQTT──► Mosquitto ──► Node-RED ──HTTP──► Backend (FastAPI + AI) ──► PostgreSQL ◄── Grafana
   (the scale)            (post office)   (driver)            (the brain)              (cabinet)      (screen)
```

| Part | Job | Open it | Login |
|---|---|---|---|
| **Mosquitto** | Receives sensor messages (MQTT) | `localhost:1883` (MQTT Explorer app) | none |
| **Node-RED** | Sends messages to the backend, handles alerts, **test buttons** | http://localhost:1880 | none |
| **Backend** | Checks data: anomalies, fill forecast, value € | http://localhost:8000/docs | none |
| **PostgreSQL** | Saves everything | `localhost:5432` | compactor / compactor, db `compactor` |
| **Adminer** | Look inside the database in the browser | http://localhost:8080 | System *PostgreSQL*, server `postgres`, user/password `compactor`, db `compactor` |
| **Grafana** | Dashboard | http://localhost:3000 | none (admin/admin to edit) |

## Start / stop

Install **Docker Desktop**, then in this folder (settings: copy `.env.example` → `.env` if you want to change passwords/ports — optional):
```powershell
docker compose up -d --build     # start everything in the background
docker compose ps                # all 6 should be "healthy" / "running"
docker compose logs -f backend   # watch one part's messages (Ctrl+C to stop watching)
docker compose down              # stop (data is kept)
docker compose down -v           # stop AND delete all data (fresh start)
```

## Test without a sensor

1. Open **Node-RED** → http://localhost:1880
2. Click the **square button** on the left of a test node, e.g. *Normal: C1 800 kg, 50% full*
3. Open the **🐞 debug** tab on the right → you see alerts for warnings
4. Open **Grafana** → the numbers update within 10 seconds

Or from the terminal:
```powershell
docker compose exec mosquitto mosquitto_pub -t compactor/C1/reading -m '{\"compactor_id\":\"C1\",\"weight_kg\":800,\"fill_pct\":50}'
```

## Connect the real sensor (ESP32)
1. Open `firmware/compactor_node/` in VS Code with the **PlatformIO** extension
2. Copy `include/config.h.example` → `include/config.h`, fill in Wi-Fi and your laptop IP (`ipconfig`)
3. Click **Upload** (libraries install automatically)
4. Laptop and ESP32 on the same Wi-Fi; allow port 1883 in Windows firewall
5. Grafana → Status table → "Last seen" turns red if a sensor stops sending

## Add an AI model (no code change)
1. Collect a few days of normal readings
2. `pip install -r training/requirements.txt` then `python training/train_anomaly.py`
3. Load it: open http://localhost:8000/docs → `POST /api/models/reload` → Execute
4. Unusual readings now also get an `ml_anomaly` alert. See `models/README.md`

## Who owns what

| Area | Folder | Owner |
|---|---|---|
| Hardware (load cell, ESP32) | `firmware/` | _name_ |
| Data flow & alerts | `nodered/`, `mosquitto/` | _name_ |
| Backend & database | `backend/app/main.py`, `service.py`, `db.py` | _name_ |
| AI: rules, forecast, value, ML models | `backend/app/ai/`, `training/`, `models/` | _name_ |
| Dashboard | `grafana/` | _name_ |
| Pitch & business model | `docs/` | _name_ |
| **`main` keeper** (merges PRs) | — | _name_ |

## Saving your changes in Grafana / Node-RED
- **Node-RED:** click **Deploy** → it saves into `nodered/flows.json` → commit that file.
- **Grafana:** Dashboard settings → **JSON Model** → copy into `grafana/dashboards/compactor.json` → commit.

## Backend without Docker (for coding / tests)
```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
pytest                              # run tests
uvicorn app.main:app --reload       # uses a local SQLite file
```

## The 5 team rules
1. **`CONTRACT.md` is law.** Change the data format only by PR to `CONTRACT.md` first.
2. **Never push to `main`.** Branch → Pull Request → keeper merges.
3. **Merge small and often** — at least twice a day.
4. **`main` must always run.**
5. **Ask after 30 minutes stuck.**

More: [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`CONTRACT.md`](CONTRACT.md) · [`CLAUDE.md`](CLAUDE.md) · [`docs/PLAN.md`](docs/PLAN.md)

## Troubleshooting
- **"port is already allocated":** another project uses the port → `docker ps`, stop it.
- **Grafana empty:** send a few test readings; check time range (top right).
- **Backend error:** `docker compose logs backend`
- **ESP32 can't connect:** same Wi-Fi, correct laptop IP, firewall allows port 1883.
