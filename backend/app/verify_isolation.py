"""Tries to break tenant isolation on the RUNNING stack: real Grafana, real Postgres, real backend. Changes no data.
    docker compose exec backend python -m app.verify_isolation
Needs the demo customers (python -m app.seed_demo) with DEMO_CUSTOMER1_PASSWORD / 2 set. Exit code 1 if anything fails."""
import json
import os
import re
import sys
from pathlib import Path

import httpx

API = os.getenv("VERIFY_API", "http://localhost:8000")
GF = os.getenv("GRAFANA_URL", "http://grafana:3000")
ADMIN = (os.getenv("GRAFANA_ADMIN_USER", "admin"), os.getenv("GRAFANA_ADMIN_PASSWORD", ""))
PORTAL_ADMIN = (os.getenv("PLATFORM_ADMIN_EMAIL", "admin@compactor.local"), os.getenv("PLATFORM_ADMIN_PASSWORD", ""))
A = {"email": "customer1@demo.local", "pw": os.getenv("DEMO_CUSTOMER1_PASSWORD", ""), "own": {"A-101", "A-102"}}
B = {"email": "customer2@demo.local", "pw": os.getenv("DEMO_CUSTOMER2_PASSWORD", ""), "own": {"B-201", "B-202"}}
ADMIN_UIDS = ["smart-compactor", "live-pickups", "live-money", "edge-live", "value-cockpit", "cockpit-cost", "cockpit-operators",
              "cockpit-actions", "admin-customers"]
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""), flush=True)


def grafana_session(email, password) -> httpx.Client:
    """Logs in the way a browser does."""
    c = httpx.Client(base_url=GF, timeout=30)
    r = c.post("/login", json={"user": email, "password": password})
    assert r.status_code == 200, f"Grafana login failed for {email}: {r.status_code}"
    return c


def sql(c, query, ds="tenant-pg", headers=None):
    """Returns (rows, error). The same request a Viewer's browser can send with any SQL it likes."""
    r = c.post("/api/ds/query", headers=headers or {}, json={
        "from": "now-30d", "to": "now",
        "queries": [{"refId": "A", "datasource": {"uid": ds}, "rawSql": query, "format": "table", "rawQuery": True}]})
    try:
        res = r.json()
    except ValueError:
        return None, f"http {r.status_code}"
    a = res.get("results", {}).get("A", {})
    if r.status_code != 200 or a.get("error"):
        return None, a.get("error") or res.get("message") or f"http {r.status_code}"
    rows = []
    for frame in a.get("frames", []):
        cols = frame.get("data", {}).get("values", [])
        rows += list(zip(*cols)) if cols else []
    return rows, None


def api_token(email, password):
    r = httpx.post(API + "/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"portal login failed for {email}: {r.status_code}"
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_anonymous():
    print("\n== Nobody signed in ==")
    for path in ("/api/org", "/api/search", "/api/dashboards/uid/smart-compactor", "/api/datasources"):
        check(f"Grafana {path} refused", httpx.get(GF + path, timeout=20).status_code == 401)
    r = httpx.post(GF + "/api/ds/query", json={"queries": [{"refId": "A", "datasource": {"uid": "compactor-pg"}, "rawSql": "SELECT 1"}]}, timeout=20)
    check("Grafana query refused", r.status_code == 401)
    for path in ("/api/compactors", "/api/alerts", "/api/pickups", "/api/compactors/A-101/readings", "/api/cockpit/actions"):
        check(f"API {path} refused", httpx.get(API + path, timeout=20).status_code == 401)
    r = httpx.post(API + "/api/readings", json={"compactor_id": "A-101", "weight_kg": 1}, timeout=20)
    check("API rejects a reading without the machine key", r.status_code == 401)


def test_api():
    print("\n== Backend API ==")
    admin = api_token(*PORTAL_ADMIN)
    seen = {s["compactor_id"] for s in httpx.get(API + "/api/compactors", headers=admin, timeout=20).json()}
    check("1 Admin sees every customer", A["own"] | B["own"] <= seen, str(seen))
    for me, other, label in ((A, B, "Customer 1"), (B, A, "Customer 2")):
        h = api_token(me["email"], me["pw"])
        seen = {s["compactor_id"] for s in httpx.get(API + "/api/compactors", headers=h, timeout=20).json()}
        check(f"2 {label} sees exactly its own devices", seen == me["own"], str(seen))
        for name, path in (("alerts", "/api/alerts?limit=1000"), ("pickups", "/api/pickups?limit=1000")):
            got = {x["compactor_id"] for x in httpx.get(API + path, headers=h, timeout=20).json()}
            check(f"3/4 {label} {name} only its own", got and got <= me["own"], str(got))
        for dev in sorted(other["own"]) + ["C1"]:
            for path in (f"/api/compactors/{dev}", f"/api/compactors/{dev}/readings", f"/api/alerts?compactor_id={dev}"):
                check(f"5 {label} GET {path} -> 404", httpx.get(API + path, headers=h, timeout=20).status_code == 404)
        check(f"5 {label} admin API -> 403", httpx.get(API + "/api/admin/tenants", headers=h, timeout=20).status_code == 403)
        check(f"5 {label} Europress analysis -> 403", httpx.get(API + "/api/cockpit/actions", headers=h, timeout=20).status_code == 403)


def org_ids():
    r = httpx.get(GF + "/api/orgs", auth=ADMIN, timeout=20).json()
    return {o["name"]: o["id"] for o in r}


def test_grafana(me, other, label, orgs, my_org, other_org):
    print(f"\n== Grafana as {label} ==")
    c = grafana_session(me["email"], me["pw"])
    mine = c.get("/api/user/orgs").json()
    check("member of one org only, as Viewer", [(o["orgId"], o["role"]) for o in mine] == [(my_org, "Viewer")], str(mine))
    uids = sorted(d["uid"] for d in c.get("/api/search?type=dash-db").json())
    check("sees exactly the 7 customer pages", len(uids) == 7 and all(u.startswith("cust-") for u in uids), str(uids))
    home = c.get("/api/dashboards/home").json()
    check("home page is the customer overview, not the admin page", "cust-overview" in str(home.get("redirectUri")), str(home)[:120])

    for uid in ADMIN_UIDS:
        check(f"6 direct URL {uid} denied", c.get(f"/api/dashboards/uid/{uid}").status_code in (403, 404))
    for org in (1, other_org):
        check(f"6 switch to org {org} denied", c.post(f"/api/user/using/{org}").status_code in (401, 403))
        r = c.get("/api/search?type=dash-db", headers={"X-Grafana-Org-Id": str(org)})
        got = {d["uid"] for d in r.json()} if r.status_code == 200 else set()
        check(f"6 org header {org} gives no admin pages", not any(u in got for u in ADMIN_UIDS), str(got))
        r = c.get(f"/api/dashboards/uid/smart-compactor?orgId={org}")
        check(f"6 ?orgId={org} URL denied", r.status_code in (401, 403, 404))
        rows, err = sql(c, "SELECT count(*) FROM readings", ds="compactor-pg", headers={"X-Grafana-Org-Id": str(org)})
        check(f"7 superuser datasource through org header {org} refused", err is not None, str(rows))
    check("still in its own org after the attempts", c.get("/api/org").json().get("id") == my_org)

    rows, err = sql(c, "SELECT count(*) FROM readings", ds="compactor-pg")
    check("7 admin datasource refused", err is not None, str(rows))
    r = c.get("/api/datasources/uid/compactor-pg")
    check("7 admin datasource not visible", r.status_code in (403, 404))
    check("cannot add a datasource", c.post("/api/datasources", json={"name": "x", "type": "grafana-postgresql-datasource"}).status_code in (401, 403))
    check("cannot edit its datasource", c.put("/api/datasources/uid/tenant-pg", json={"name": "x", "type": "grafana-postgresql-datasource"}).status_code in (401, 403))
    check("cannot save a dashboard", c.post("/api/dashboards/db", json={"dashboard": {"title": "x"}}).status_code in (401, 403))
    check("cannot create an org", c.post("/api/orgs", json={"name": "x"}).status_code in (401, 403))
    check("cannot list all users", c.get("/api/users").status_code in (401, 403))
    check("cannot list org members", c.get("/api/org/users").status_code in (401, 403))

    rows, err = sql(c, "SELECT DISTINCT compactor_id FROM tenant_api.readings")
    check("2 own readings arrive", not err and {r[0] for r in rows} == me["own"], f"{rows} {err}")
    for table, col in (("compactors", "id"), ("compactor_status", "compactor_id"), ("alerts", "compactor_id"), ("pickups", "compactor_id")):
        rows, err = sql(c, f"SELECT DISTINCT {col} FROM tenant_api.{table}")
        check(f"7 tenant_api.{table} holds only its own", not err and rows and {r[0] for r in rows} <= me["own"], f"{rows} {err}")

    victim = sorted(other["own"])[0]
    empty = {
        "dashboard variable with another device": f"SELECT * FROM tenant_api.readings WHERE compactor_id IN ('{victim}')",
        "OR 1=1 style filter": f"SELECT * FROM tenant_api.readings WHERE compactor_id = '{victim}' OR (1=1 AND compactor_id = '{victim}')",
        "planner statistics": "SELECT * FROM pg_stats WHERE schemaname = 'public' AND tablename IN ('readings', 'users', 'tenant_devices')",
    }
    for name, q in empty.items():
        rows, err = sql(c, q)
        check(f"7 {name}: no rows", not rows, str(rows)[:100])

    denied = {
        "base table readings": "SELECT * FROM public.readings",
        "base table alerts": "SELECT * FROM public.alerts",
        "base table pickups": "SELECT * FROM public.pickups",
        "accounts": "SELECT email, password_hash FROM public.users",
        "sessions": "SELECT * FROM public.auth_sessions",
        "tenant list": "SELECT * FROM public.tenants",
        "device owners": "SELECT * FROM public.tenant_devices",
        "SET ROLE superuser": "SET ROLE compactor; SELECT * FROM public.readings",
        "SET ROLE shared group": "SET ROLE tenant_reader",
        "SET SESSION AUTHORIZATION": "SET SESSION AUTHORIZATION compactor; SELECT * FROM public.readings",
        "read a server file": "SELECT pg_read_file('/etc/passwd')",
        "COPY from a program": "COPY (SELECT 1) TO PROGRAM 'id'",
        "create a table": "CREATE TABLE tenant_api.x (a int)",
        "create in public": "CREATE TABLE public.x (a int)",
        "temp table": "CREATE TEMP TABLE x (a int)",
        "temp function to leak rows": "CREATE FUNCTION pg_temp.leak(text) RETURNS bool AS 'SELECT true' LANGUAGE sql",
        "insert": "INSERT INTO tenant_api.materials VALUES ('x', 1, 1, 1, 1)",
        "update despite read-only off": "SET default_transaction_read_only = off; UPDATE tenant_api.readings SET weight_kg = 0",
        "delete despite read-only off": "SET default_transaction_read_only = off; DELETE FROM tenant_api.readings",
        "replace a view": "CREATE OR REPLACE VIEW tenant_api.my_devices AS SELECT id AS compactor_id FROM public.compactors",
        "alter own role": "ALTER ROLE CURRENT_USER SUPERUSER",
        "grant itself the owner": "GRANT compactor TO CURRENT_USER",
    }
    for name, q in denied.items():
        rows, err = sql(c, q)
        check(f"7 {name}: denied", err is not None, str(rows)[:100])

    rows, _ = sql(c, "SELECT query FROM pg_stat_activity WHERE usename <> current_user AND query NOT IN ('', '<insufficient privilege>')")
    check("7 cannot read other sessions' SQL", not rows, str(rows)[:100])
    settings = c.get("/api/frontend/settings").text
    check("admin datasource not in the page settings", "compactor-pg" not in settings)
    r = c.get("/api/datasources/uid/tenant-pg")
    check("database password is not readable", r.status_code in (403, 404) or me["pw"] not in r.text and '"password":"' not in r.text.replace(" ", ""))
    check("no datasource proxy into Postgres", c.get("/api/datasources/proxy/uid/tenant-pg/").status_code >= 400)
    rows, _ = sql(c, "SELECT rolname FROM pg_roles WHERE rolcanlogin")
    names = [r[0] for r in rows or []]
    check("role names reveal no customer", all(re.fullmatch(r"t_[0-9a-f]{16}", n) or n == "compactor" for n in names), str(names))
    rows, _ = sql(c, "SELECT current_user, session_user")
    check("runs as its own unprivileged role", rows and re.fullmatch(r"t_[0-9a-f]{16}", rows[0][0]), str(rows))
    return c


def panel_sql(dash):
    def walk(panels):
        for p in panels:
            yield from walk(p.get("panels", []))
            for t in p.get("targets", []):
                if t.get("rawSql"):
                    yield p.get("title", ""), t["rawSql"], t.get("format", "table")
    return list(walk(dash.get("panels", [])))


def run_panel(c, ds, q, fmt):
    r = c.post("/api/ds/query", json={"from": "now-30d", "to": "now", "queries": [
        {"refId": "A", "datasource": {"uid": ds}, "rawSql": q, "format": fmt, "rawQuery": True}]})
    a = r.json().get("results", {}).get("A", {})
    return a.get("error") if r.status_code != 200 or a.get("error") else None


def test_customer_panels(c, me, label):
    print(f"\n== Every panel for {label} ==")
    devices = ",".join(f"'{d}'" for d in sorted(me["own"]))
    n = bad = 0
    for f in sorted((Path(__file__).parent / "tenant_dashboards").glob("*.json")):
        dash = c.get(f"/api/dashboards/uid/{json.loads(f.read_text())['uid']}").json()["dashboard"]
        for title, q, fmt in panel_sql(dash):
            n += 1
            err = run_panel(c, "tenant-pg", q.replace("$device", devices), fmt)
            if err:
                bad += 1
                check(f"{dash['title']} / {title}", False, err[:160])
    check(f"all {n} customer panels run", bad == 0)


def test_admin_panels():
    print("\n== 8 Existing admin pages (Grafana admin) ==")
    c = httpx.Client(base_url=GF, auth=ADMIN, timeout=60)
    rows, err = sql(c, "SELECT count(DISTINCT compactor_id) FROM readings", ds="compactor-pg")
    check("admin datasource reads every customer", not err and rows[0][0] >= 4, f"{rows} {err}")
    n = waiting = bad = 0
    for item in c.get("/api/search?type=dash-db").json():
        dash = c.get(f"/api/dashboards/uid/{item['uid']}").json()["dashboard"]
        for title, q, fmt in panel_sql(dash):
            q = re.sub(r"\$\{?(customer|operator|problem|material)(:\w+)?\}?", "'x'", q)
            err = run_panel(c, "compactor-pg", q, fmt)
            n += 1
            if err and re.search(r'relation "cp_\w+" does not exist', err):
                waiting += 1          # needs the Europress dataset: docker compose run --rm analytics
            elif err:
                bad += 1
                check(f"{dash['title']} / {title}", False, err[:160])
    check(f"{n} admin panels: {n - waiting - bad} run, {waiting} wait for the Europress tables, {bad} broken", bad == 0)


def main():
    if not (A["pw"] and B["pw"]):
        sys.exit("Set DEMO_CUSTOMER1_PASSWORD and DEMO_CUSTOMER2_PASSWORD first (python scripts/init_env.py)")
    test_anonymous()
    test_api()
    orgs = org_ids()
    one, two = orgs["Demo Customer 1"], orgs["Demo Customer 2"]
    c1 = test_grafana(A, B, "Customer 1", orgs, one, two)
    c2 = test_grafana(B, A, "Customer 2", orgs, two, one)
    test_customer_panels(c1, A, "Customer 1")
    test_customer_panels(c2, B, "Customer 2")
    test_admin_panels()
    failed = results.count(False)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
