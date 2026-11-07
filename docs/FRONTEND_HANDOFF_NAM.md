# Frontend handoff for Nam

Branch: `feature/live-pickups-ux`, based on `feature/compactor-framework` at `3cfdb30`. **Read `README_NAM.md` first:** it does not contain your commit `f4f653b` yet.
Portal and Cockpit were redesigned without firmware. Everything marked "Requires Nam" below still needs your board or the Europress dataset.

## A. Architecture

No framework and no build step: plain HTML, CSS and JavaScript served by FastAPI.

```
portal.js / cockpit.js        screens: call SC.data only, never fetch()
        │
     SC.data (data.js)        one adapter + normalize step
     ├── live provider        FastAPI, session cookie         default, always in production
     └── mock provider        dev/mock.js + dev/fixtures.json in the browser, dev only
```

| File | Purpose |
|---|---|
| `backend/app/static/portal.html`, `cockpit.html` | Thin entry pages, same routes `/portal` and `/cockpit` |
| `backend/app/static/assets/ui.css` | Design system: tokens and components |
| `backend/app/static/assets/ui.js` | Shell, toast, confirm dialog, validation, states, `SC.SOURCE` wording |
| `backend/app/static/assets/data.js` | Adapter, live provider, `normalize`, `ApiError` |
| `backend/app/static/assets/portal.js`, `cockpit.js` | Screens |
| `backend/app/static/dev/` | Mock provider and fixtures. Served only when mock mode is on |

Rules that keep this safe:
- Hiding a button is for clarity only. The backend decides permissions.
- Anything placed in `innerHTML` goes through `SC.esc`.
- A failed live call throws `ApiError` and the screen shows an error. There is no path from live to mock.

### Design tokens

| Role | Value | Note |
|---|---|---|
| Navy | `#142A43` | Sidebar, headings |
| Teal | `#076C78` | Primary actions, links (5.71:1 on the page background) |
| Green / amber / red | `#1A7A55` / `#8A5A00` / `#B93C3C` | Text and badges, each at least 4.9:1 |
| Background / text | `#F5F7FA` / `#1B2838` | |
| Spacing | 4, 8, 12, 16, 24, 32 px | `--s1` to `--s6` |
| Font | System stack | No web font, so it works offline on the hotspot |

Status is always written in words too, never colour alone.

### Data labels

| Label | Meaning | Used for today |
|---|---|---|
| **Real** | Recorded by the system | Accounts, decisions, device connection |
| **Estimated** | Calculated with placeholder prices or factors | Value, CO₂, fill forecast |
| **Simulated** | Not from physical hardware or a real operator | Weight (load cell is simulated in firmware), trucks, invoices, demo seed, Europress dataset |

**No weight is Real yet.** When a physical load cell is connected, update `SC.SOURCE.weight` in `ui.js`, `SOURCE_SQL` and `LEGEND` in
`grafana/make_tenant_pages.py`, and the "Simulated" tags in `portal.js`.

## B. Local setup

Windows PowerShell, from the repository root:
```powershell
git fetch origin
git switch feature/live-pickups-ux
python scripts/init_env.py          # adds missing secrets to .env, keeps your values, prints none
docker compose up -d --build
docker compose exec backend python -m app.seed_demo    # optional demo customers
```

**Your laptop already has a Grafana volume**, and Grafana reads its admin password only on first start. Open `.env`, copy
`GRAFANA_PASS`, then run:
```powershell
docker compose exec grafana grafana cli admin reset-admin-password "<GRAFANA_PASS value>"
```

**Check `.env` keeps `DEMO_TIME_SCALE=60`, `READING_INTERVAL_H` and `DEVICE_KEYS`.** `init_env.py` does not change them.

| Page | URL |
|---|---|
| Portal | http://localhost:8000/portal |
| Cockpit (admins) | http://localhost:8000/cockpit |
| Grafana | http://localhost:3000 |
| API docs | http://localhost:8000/docs |

The Grafana link in the Portal comes from `PUBLIC_GRAFANA_URL`.

## C. Mode switching

**Live is the default.** Keep it, and you need nothing else.

Mock needs both conditions:
1. In `.env`: `FRONTEND_MOCK=true`, then `docker compose up -d backend`
2. In the URL: `http://localhost:8000/portal?mock=device-connected`

To go back to Live: set `FRONTEND_MOCK=false`, then `docker compose up -d backend`.

| Situation | What happens |
|---|---|
| `FRONTEND_MOCK` not true | `/dev/*` answers 404. `?mock=` shows a red notice and live data |
| `COOKIE_SECURE=true` (HTTPS) | Mock is off, whatever `FRONTEND_MOCK` says |
| Mock on, no `?mock=` in the URL | Live data, with a green LIVE chip beside the product name |
| Mock on, `?mock=` in the URL | Amber SIMULATED DATA banner on every screen, no call to `/api` |

Never set `FRONTEND_MOCK=true` for a demo or a deployment.

### Scenarios

Switch with the selector in the banner. Changes stay in browser memory and disappear on reload.

| Scenario | Shows |
|---|---|
| `signed-out` | Sign in and registration. An e-mail containing `pending` shows the waiting state; password `wrong-password` fails |
| `device-connected`, `device-offline` | Customer overview |
| `missing-measurements` | Empty values shown as `–`, never 0 |
| `no-devices` | Active account with no devices |
| `admin` | Approvals, customers, devices |
| `cockpit-pending`, `cockpit-decided`, `cockpit-no-analysis` | Cockpit states |
| `api-error`, `network-error`, `forbidden`, `loading` | Failure and loading states |

Fixture rules: mock ids start with `M-`, names contain `Mock`, alerts start with `Simulated demo:`, and text starts with `MOCK TEXT`.
`backend/tests/test_frontend.py` fails if a fixture stops matching the API.

## D. API integration

The frontend uses existing endpoints only. Sign-in sets the HttpOnly cookie `sc_session`.

| Screen | Endpoint | Who |
|---|---|---|
| Sign in, sign out, register | `POST /api/auth/login`, `/logout`, `/register` | Anyone |
| Session | `GET /api/auth/me` | Signed in |
| Customer overview | `GET /api/compactors`, `/api/alerts?limit=`, `/api/pickups?limit=` | Signed in, filtered per customer |
| Approvals | `GET /api/admin/registrations?status=`, `POST .../{id}/approve`, `.../reject` | Admin |
| Customers | `GET /api/admin/tenants`, `POST .../{id}/status`, `POST` and `DELETE .../{id}/devices` | Admin |
| Devices | `GET` and `POST /api/admin/devices` | Admin |
| Cockpit | `GET /api/cockpit/actions`, `.../{id}/evidence`, `POST .../{id}/decision` with `{decision, note}` | Admin |

Field details are in `CONTRACT.md`. Errors arrive as `{"detail": "text"}`, or a list for validation (422). `ApiError.kind` is
`network`, `auth`, `forbidden`, `notfound`, `server` or `invalid`.

**Device state is decided in the frontend:** connected if the last reading is under 2 hours old (`OFFLINE_AFTER_MS` in `data.js`).
With a reading every 10 s you may want it shorter. Check it on the board.

### Gaps in the API

| Gap | What the UI does |
|---|---|
| No `completed` state for decisions | Shows only Pending, Approved, Rejected |
| `/api/cockpit/actions` returns `[]` both when nothing was found and when analysis was never built | One empty message covering both |
| `/api/compactors` does not say where a reading came from | Portal uses one fixed message. Grafana works it out per customer from `readings` |
| No password reset | Text says to ask the administrator. There is no button |
| No endpoint to delete a device or customer | No such control |

## E. Test instructions

Backend, no firmware needed:
```powershell
docker build -f backend/Dockerfile -t sc-backend-test .
docker run --rm -v "${PWD}/backend:/t" -w /t sc-backend-test python -m pytest -q
```

Tenant isolation, on the running stack with demo customers:
```powershell
docker compose exec backend python -m app.verify_isolation
```

Adapter, needs only Node:
```powershell
cd tests/frontend
npm ci
npm run unit
```

Browser, needs Chrome or Edge:
```powershell
$env:CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:BASE = "http://localhost:8000"
node browser.mjs mock        # server with FRONTEND_MOCK=true
# then with FRONTEND_MOCK=false:
$env:CUSTOMER_EMAIL = "customer1@demo.local"; $env:CUSTOMER_PASSWORD = "<from .env>"
$env:ADMIN_EMAIL = "admin@compactor.local";   $env:ADMIN_PASSWORD = "<from .env>"
$env:OTHER_DEVICE = "B-201"
node browser.mjs live
```
Set `$env:SHOTS` to a folder to keep screenshots. The browser tests only read and use mock writes, so they change no data.

## F. Hardware integration checklist (Requires Nam)

1. [ ] Back up first: `git status` is clean, `.env` keeps your values.
2. [ ] `docker compose up -d --build`, then Grafana password reset from section B.
3. [ ] All 6 services are healthy and `INGEST_API_KEY` is set. Node-RED sends it by itself.
4. [ ] Flash only if firmware changed, with `secure_flash.ps1`. This branch does not touch firmware.
5. [ ] Readings arrive: `compactor/+/reading` → Node-RED → `readings` rows for C1, C2, C3.
6. [ ] Signatures: rows have `verified = true` when `DEVICE_KEYS` is set.
7. [ ] Admin Grafana Live pages still update.
8. [ ] Truck loop still works: booking → command on `site/S1/cmd` → board empties → pickup judged.
9. [ ] Portal, as admin: Customers → hand C1–C3 to a customer. **They have no owner until you do.**
10. [ ] Portal, as that customer: devices show Connected and values change on refresh.
11. [ ] Unplug the board: state becomes Offline after the threshold; check the threshold suits you.
12. [ ] Grafana banner for that customer says "SIMULATED load cell: real ESP32 edge processing".
13. [ ] Fill forecast in fast mode looks sensible, in site hours.
14. [ ] `docker compose run --rm analytics` with the dataset, then Cockpit shows real proposals and cards fit their text.
15. [ ] In the Cockpit approve, reject and revert one real proposal, and check the Grafana page "5 Decisions".
16. [ ] Re-run `verify_isolation`.

## G. Known limitations

| Item | Status |
|---|---|
| Real ESP32 readings in the new Portal | **Not tested.** Requires Nam |
| Truck loop end to end after these changes | **Not tested on a board.** Backend code is unchanged |
| Cockpit with real Europress proposals | **Not tested.** Only fixtures and one temporary row |
| 22 Grafana panels on `cp_*` tables | **Not tested.** Requires the dataset |
| Task B, B2, C2 results | **Not re-run.** `audit/` and `analytics/` are unchanged |
| Windows commands in this file | **Not run.** Written from a Mac |

Other limits:
- **MQTT has no login.** Anyone on the network can read and publish every customer's readings.
- Customers sign in twice, Portal and Grafana.
- Portal has no dark mode, and UI text is in English.
- The admin Grafana page has a fixed `localhost:8000` portal link (`grafana/make_tenant_pages.py`).
- Admin Live pages are unchanged. They already say that invoices are simulated and prices are placeholders, but not that the load cell is simulated.
- `python -m app.seed_demo` re-sends dashboards to the two demo orgs only. Other customers keep theirs until you push them.
- **Regenerating Grafana:** `make_live_pages.py` reads `DEMO_TIME_SCALE` from `.env`. With 1 it rewrites `compactor.json` for real time. Keep 60 when regenerating.
- Multi-tenant limits are in `docs/MULTI_TENANT.md`, including Rahti, which is not migrated.

### Live 2 · Pickups candidate

A redesigned page waits in `grafana/candidates`, and Grafana does not load it. Build it on your machine, so it states your
`DEMO_TIME_SCALE`, and read `grafana/candidates/README.md` before applying it. Writing into `grafana/dashboards` goes live within seconds.

### Troubleshooting

| Problem | Fix |
|---|---|
| Portal says "Cannot reach the server" | `docker compose ps`, then `docker compose logs backend` |
| Page looks unstyled | Open `/assets/ui.css`. A 404 means the backend is old: `docker compose up -d --build backend` |
| Red "Mock mode is switched off" | Expected in Live. Remove `?mock=` from the URL |
| Approving gives 503 | Message names the setting. Usually `GRAFANA_PASS` or `INGEST_API_KEY` |
| Approving gives 502 | Backend cannot log in to Grafana: run the password reset in section B |
| No readings after upgrading | `docker compose up -d nodered` so it gets `INGEST_API_KEY`, then check its debug tab |
| Dashboards "not ready" after first sign-in | Sign in to the Portal again. Check backend logs for "Grafana sync failed" |

## H. File changes

Compared with `feature/multi-tenant-auth`.

| File | Change |
|---|---|
| `backend/app/static/assets/*` | **New:** `ui.css`, `ui.js`, `data.js`, `portal.js`, `cockpit.js` |
| `backend/app/static/dev/*` | **New:** `mock.js`, `fixtures.json` (dev only) |
| `backend/app/static/portal.html`, `cockpit.html` | Rewritten as entry pages |
| `backend/app/main.py` | Serves `/assets`, and `/dev/*` only when mock is on. No business logic |
| `backend/app/seed_demo.py` | Marks demo data as simulated, re-sends dashboards to demo orgs |
| `grafana/make_tenant_pages.py`, `backend/app/tenant_dashboards/*.json` | Real, Estimated, Simulated labels. Removes the wrong "Expected full" time |
| `docker-compose.yml`, `.env.example` | Adds `FRONTEND_MOCK`, default false |
| `backend/tests/test_frontend.py` | **New:** mock is dev-only, fixtures match the API |
| `tests/frontend/*` | **New:** adapter and browser tests |
| `docs/FRONTEND_HANDOFF_NAM.md`, `README.md`, `CLAUDE.md` | This guide and links to it |

Not touched: firmware, MQTT topics, Node-RED flows, database schema, business logic, auth, `audit/`, `analytics/`, Grafana provisioning, other dashboards.
