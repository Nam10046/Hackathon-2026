# Multi-tenant customer platform

Customers sign in and see only their own compactors. Admins see everyone. The ESP32, MQTT and Node-RED ingestion path is
unchanged, except that Node-RED now sends the machine key.

## How isolation works

```
Customer ─► Grafana org of that customer ─► datasource tenant-pg ─► Postgres role t_<random> ─► tenant_api.* views
Admin    ─► Grafana org 1 ───────────────► datasource compactor-pg ─► all tables
Customer ─► Backend API (session) ─► filtered by tenant_devices
```

A Grafana Viewer can send **any SQL** to its datasource (`POST /api/ds/query`), so dashboard variables protect nothing.
The boundary is in Postgres: the tenant role has no rights on base tables, only on `tenant_api` views, and each view keeps
the rows of devices owned by `current_user`. Every org gets the same dashboards; only the role behind `tenant-pg` differs.

| Layer | Control |
|---|---|
| Postgres | One read-only role per customer, `security_barrier` views, no temp tables, no `SET ROLE`, 10 connections |
| Grafana | One org per customer, members are Viewers, anonymous access / sign-up / org creation / snapshots off |
| Backend | Data endpoints need a session; another customer's device answers 404, same as an unknown id |
| Writes | Readings need `X-API-Key`. Europress analysis and model health are admin-only. Cockpit decisions need a signed-in admin and log that admin's e-mail |
| Onboarding | Registration gives nothing. Only an admin sets the tenant and the devices |
| Fail closed | Customers are refused (503) while `INGEST_API_KEY` is empty, `GRAFANA_PASS` is weak, or Grafana is anonymous |

## Setup

```bash
python scripts/init_env.py        # fills .env with strong secrets, prints none of them
docker compose up -d --build
docker compose exec backend python -m app.seed_demo          # optional: two demo customers
docker compose exec backend python -m app.verify_isolation   # attacks the running stack, changes no data
```

| What | Where | Login |
|---|---|---|
| Portal | http://localhost:8000/portal | `admin@compactor.local` / `PLATFORM_ADMIN_PASSWORD` |
| Grafana, admin | http://localhost:3000 | `admin` / `GRAFANA_PASS` |
| Demo customer 1 (A-101, A-102) | both | `customer1@demo.local` / `DEMO_CUSTOMER1_PASSWORD` |
| Demo customer 2 (B-201, B-202) | both | `customer2@demo.local` / `DEMO_CUSTOMER2_PASSWORD` |

All passwords are in your local `.env`. Demo data is made up and uses its own device ids, so ESP32 data (C1-C3) is not mixed
with it. C1-C3 have no owner until an admin hands them to a customer in the portal; until then only admins see them.

### Upgrading a laptop that already ran the stack

Grafana reads its admin password only on first start, so an old volume keeps the old password:
```bash
python scripts/init_env.py
docker compose up -d --build
set -a; . ./.env; set +a
docker compose exec grafana grafana cli admin reset-admin-password "$GRAFANA_PASS"
```
No data is reset. Anonymous viewing is now off: everyone, including judges, needs a login.

## Onboarding a customer

1. The customer asks for an account at `/portal`. The company name they type proves nothing.
2. An admin opens `/portal`, picks a new or existing customer, hands over free devices, and approves. The backend creates the
   Postgres role, Grafana org, datasource, folder, 7 dashboards and home page. No JSON is edited.
3. The customer signs in at `/portal` once, which creates their Grafana account with the same password, then opens the dashboards.

New device: "Add a device" in the portal, then send readings to `compactor/<id>/reading`.

Changed dashboards: edit `grafana/make_tenant_pages.py` and run it. New customers get the new version.
Existing customers: `docker compose exec backend python -c "from app import provision; provision.push_dashboards(<org id>)"`.

## Check isolation in a browser

Use two private windows.
1. **Window 1:** sign in to Grafana as customer 1. Overview shows 2 compactors, A-101 and A-102.
2. **Window 2:** sign in as customer 2. It shows B-201 and B-202.
3. **Window 1:** open `/d/smart-compactor`, `/d/value-cockpit?orgId=1` and `/d/admin-customers`. All say *Not found*.
4. **Window 1:** on *2 · Live monitoring*, add `&var-device=B-201` to the URL. The panels stay empty.
5. **Window 1:** with the portal signed in, open `http://localhost:8000/api/compactors/B-201`. Answer: 404.
6. Sign in to Grafana as `admin`, open **Hackathon › Admin · All customers**. Every customer is listed.

## Undo

```bash
docker compose exec -T postgres psql -U compactor -d compactor < backend/app/migrations/0001_tenant_api.down.sql
```
Removes tenant views, roles, accounts and ownership. Readings, alerts, pickups and compactors stay. The next backend start
installs the empty tenant layer again. Delete customer orgs in Grafana yourself (Server admin › Organizations).

## Known limitations

- **MQTT is still open.** Anyone who can reach port 1883 can read and publish every customer's readings, without any
  login. Fixing it needs broker passwords and ACLs plus a firmware config change. Keep port 1883 on a private network.
  Signatures (`DEVICE_KEYS`) flag forged readings but do not reject them.
- **No TLS.** Put a reverse proxy with HTTPS in front and set `COOKIE_SECURE=true` before real use.
- **Two sign-ins**, portal and Grafana. A password changed inside Grafana does not reach the portal. Next step: OIDC.
- **No e-mail verification or password reset.** The admin's approval is the identity check.
- **Registration has no per-address rate limit**, only a cap of 200 pending requests, which an attacker could fill.
- **Reassigning a device shows its history to the new owner.** The portal has no reassign button; a device cannot have two owners.
- **Shared database.** A customer can raise its own `statement_timeout` and load the server with heavy queries, within 10
  connections. It can also see table names and approximate total row counts in `pg_catalog`, but no customer's rows.
- **Grafana's `secret_key` is the default.** Set `GF_SECURITY_SECRET_KEY` on a fresh install; changing it later breaks stored secrets.
- **Rahti is not migrated.** `deploy/rahti/rahti.yaml` still enables anonymous Grafana, so do not create customers there.
  A new backend image there also needs `PLATFORM_ADMIN_PASSWORD`, or `/cockpit` has no one who can sign in.
- **PostgreSQL 16+** is required (`WITH SET FALSE`). TigerData is not tested and must allow `CREATE ROLE`.
