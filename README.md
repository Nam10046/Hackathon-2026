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
| **Portal** | Customer sign-in and admin approvals | http://localhost:8000/portal | see `docs/MULTI_TENANT.md` |
| **Adminer** | Look inside the database in the browser | http://localhost:8080 | System *PostgreSQL*, server `postgres`, user/password `compactor`, db `compactor` |
| **Grafana** | Dashboard | http://localhost:3000 | `admin` / `GRAFANA_PASS` from `.env` |

## Start / stop

Install **Docker Desktop**, then in this folder (settings: copy `.env.example` → `.env` if you want to change passwords/ports — optional):
```powershell
docker compose up -d --build     # start everything in the background
docker compose ps                # all 6 should be "healthy" / "running"
docker compose logs -f backend   # watch one part's messages (Ctrl+C to stop watching)
docker compose down              # stop (data is kept)
docker compose down -v           # stop AND delete all data (fresh start)
```

## Customer accounts
Customers sign in and see only their own compactors: [`docs/MULTI_TENANT.md`](docs/MULTI_TENANT.md).
```powershell
python scripts/init_env.py        # once: strong passwords in .env
docker compose up -d --build
docker compose exec backend python -m app.seed_demo   # optional demo customers
```
Portal: http://localhost:8000/portal. Grafana now needs a login, and most API reads need a session.
Frontend structure, mock mode and tests: [`docs/FRONTEND_HANDOFF_NAM.md`](docs/FRONTEND_HANDOFF_NAM.md).

## 📦 Hackathon submission
Everything the judges need is in [`submission/`](submission/README.md): weighing concept, software demo notes,
business case, licences and assumptions.

## Customer Value Cockpit (the Europress dataset)
1. Unzip the Europress participants package into `europress/` (git-ignored)
2. `docker compose run --rm analytics` (≈1 min)
3. Grafana → **Customer Value Cockpit** (http://localhost:3000/d/value-cockpit) · approve proposals at **http://localhost:8000/cockpit**

Details: [`analytics/README.md`](analytics/README.md)

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

## Shared database for the team (TigerData)
By default each laptop has its own local database. To make **everyone use the same data**, copy
`.env.example` → `.env` and fill in the TigerData block (host, port, `DB_SSLMODE=require`, user, password, `tsdb`),
then `docker compose up -d`. Never commit `.env`.

## Online server for the team (CSC Rahti)
Backend + Grafana + database can run on Rahti, so everyone (and the judges) open the same links.
Step by step: [`deploy/rahti/README.md`](deploy/rahti/README.md)

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

## Team audit pipeline (`audit/`)

Our teammate's analysis code for Task B (problems), B2 (waste-company scorecard) and C2 (contract actions). It works
only with data known on each decision date (as-of snapshots, with a leakage test) and beats the organisers' baselines
(B 0.82 vs 0.78, B2 96.3 vs 67.8, C2 regret €12 vs €240). The cockpit reads its outputs.

```powershell
docker compose run --rm analytics        # runs the audit (≈ 5 min, first time only) and builds the cockpit tables
# or without Docker:
pip install -r audit/requirements.txt
python analytics/run_all.py               # add --refresh to recompute the audit
python -m pytest audit/tests -q           # 14 tests incl. "no future data"
```
Details (Vietnamese): `audit/README.md`. Results: `submission/02_software_demo.md` §6.
