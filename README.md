# Smart Compactor — Hackathon 2026 (Europress Group challenge)

> **Pitch:** We tell companies what their waste weighs and is worth **before the truck leaves** — and warn them when something is wrong.

```
 Load cell + ESP32 ─┐
                    ├─MQTT─► Mosquitto ─► Node-RED ─HTTP─► FastAPI backend ─► PostgreSQL ◄─ Grafana
 Simulator ─────────┘                    (alerts)        (anomaly, forecast,              (dashboard)
                                                           value)
```

## Quick start (everything in one command)

Install **Docker Desktop**, then:
```bash
docker compose --profile sim up --build
```
This starts all services **plus the simulator** (7 days of fake history + live data every 5 s).

| Open | What | Login |
|---|---|---|
| http://localhost:3000 | **Grafana dashboard** | none needed (admin/admin to edit) |
| http://localhost:1880 | Node-RED flows | — |
| http://localhost:8000/docs | Backend API (try it in the browser) | — |
| `localhost:5432` | PostgreSQL | compactor / compactor |
| `localhost:1883` | MQTT broker | — |

Without fake data (real sensor only): `docker compose up --build`
Reset all data: `docker compose down -v`

## Who owns what

| Area | Folder | Owner |
|---|---|---|
| Hardware (load cell, ESP32) | `firmware/` | _name_ |
| Data flow & alerts (Node-RED, MQTT) | `nodered/`, `mosquitto/` | _name_ |
| Backend & database | `backend/app/main.py`, `service.py`, `db.py` | _name_ |
| AI: anomaly, forecast, value | `backend/app/ai/`, `simulator/` | _name_ |
| Dashboard | `grafana/` | _name_ |
| Pitch & business model | `docs/` | _name_ |
| **`main` keeper** (merges PRs) | — | _name_ |

## What each part does now (and what to improve)

| Part | Works now | Next ideas |
|---|---|---|
| `firmware/` | Reads load cell + ultrasonic, sends MQTT | Calibrate, build the demo box |
| `nodered/` | MQTT → backend, filters alerts | Send alerts to email / Telegram |
| `ai/anomaly.py` | Rules: sensor fault, spike, drop, contamination, emptied | Train IsolationForest on simulator data |
| `ai/forecast.py` | Straight-line "hours to full" | Day-of-week pattern, ML model |
| `ai/value.py` | Weight × price, CO₂ | Quality penalty when contaminated |
| `grafana/` | 9-panel dashboard | Per-customer view, nicer layout |

## Run parts without Docker
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate        # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload                          # uses local SQLite file
pytest                                                 # run tests
python ../simulator/simulate.py --no-live              # fill it with history
```

## Editing Grafana / Node-RED
- **Grafana:** edit in the browser → Dashboard settings → JSON Model → copy into `grafana/dashboards/compactor.json` → commit.
- **Node-RED:** click Deploy — it saves straight into `nodered/flows.json` → commit.

## The 5 team rules
1. **`CONTRACT.md` is law.** Change the data format only by PR to `CONTRACT.md` first.
2. **Never push to `main`.** Branch → Pull Request → keeper merges.
3. **Merge small and often** — at least twice a day.
4. **`main` must always run.** Broken main = everyone's #1 task.
5. **Ask after 30 minutes stuck.**

More: [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`CONTRACT.md`](CONTRACT.md) · [`CLAUDE.md`](CLAUDE.md) · [`docs/PLAN.md`](docs/PLAN.md)

## Troubleshooting
- **Grafana empty?** Run with `--profile sim`, wait ~30 s, refresh. Time range top-right = Last 7 days.
- **Node-RED permission error (Linux/Mac):** `sudo chown -R 1000:1000 nodered`
- **ESP32 can't connect:** laptop and ESP32 on the same Wi-Fi; `MQTT_HOST` = laptop IP (`ipconfig`); allow port 1883 in Windows firewall.
