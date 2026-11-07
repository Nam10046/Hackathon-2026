"""Login, approval and tenant isolation at the API. Grafana is faked here; Postgres and real Grafana are covered by
python -m app.verify_isolation on the running stack."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from app import auth, db, grafana, provision

ADMIN = ("admin@compactor.local", "admin-password-123")
PW = "correct-horse-battery"


class FakeGrafana:
    def __init__(self):
        self.created, self.next_org, self.existing, self.orgs_deleted, self.fail = [], 10, {}, [], None

    def anonymous_is_off(self): return True

    def create_org(self, name):
        self.next_org += 1
        return self.next_org

    def delete_org(self, o): self.orgs_deleted.append(o)

    def upsert_datasource(self, o, b):
        if self.fail == "datasource":
            raise grafana.GrafanaError("boom")

    def ensure_folder(self, *a): pass
    def save_dashboard(self, *a): pass
    def set_home(self, *a): pass
    def find_user(self, email): return self.existing.get(email)

    def create_user(self, email, password, org):
        self.created.append((email, org))
        return 100 + len(self.created)

    def only_in_org(self, *a): pass
    def set_disabled(self, *a): pass


@pytest.fixture()
def fake():
    return FakeGrafana()


@pytest.fixture()
def app_client(tmp_path, monkeypatch, fake):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN[1])
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "strong-grafana-pass")
    monkeypatch.setenv("INGEST_API_KEY", "machine-key")
    monkeypatch.setattr(grafana, "client", lambda: fake)
    db.reset_engine()
    from app.main import app
    with TestClient(app) as c:
        yield c
    db.reset_engine()


def sign_in(c, email, password=PW):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    c.cookies.clear()
    return {"Authorization": "Bearer " + r.json()["token"]}


def add_device(c, h, cid):
    r = c.post("/api/admin/devices", headers=h, json={"id": cid, "name": cid, "material": "cardboard", "capacity_kg": 2000, "volume_m3": 8})
    assert r.status_code == 201, r.text


def onboard(c, h, email, company, devices):
    c.post("/api/auth/register", json={"email": email, "password": PW, "company": company})
    uid = next(u["id"] for u in c.get("/api/admin/registrations", headers=h).json() if u["email"] == email)
    r = c.post(f"/api/admin/registrations/{uid}/approve", headers=h, json={"new_tenant_name": company, "device_ids": devices})
    assert r.status_code == 200, r.text
    return r.json()["tenant_id"]


@pytest.fixture()
def world(app_client):
    """Two customers, each with one device with a reading and an alert. C3 has no owner."""
    c = app_client
    admin = sign_in(c, ADMIN[0], ADMIN[1])
    add_device(c, admin, "X1")
    add_device(c, admin, "Y1")
    onboard(c, admin, "a@one.example", "Customer One", ["X1"])
    onboard(c, admin, "b@two.example", "Customer Two", ["Y1"])
    key = {"X-API-Key": "machine-key"}
    for cid, kg in (("X1", 100), ("Y1", 200)):
        assert c.post("/api/readings", headers=key, json={"compactor_id": cid, "weight_kg": kg, "fill_pct": 10}).status_code == 200
        assert c.post("/api/readings", headers=key, json={"compactor_id": cid, "weight_kg": 99999, "fill_pct": 10}).status_code == 200
    return c, admin, sign_in(c, "a@one.example"), sign_in(c, "b@two.example")


def test_data_endpoints_need_a_login(app_client):
    for path in ("/api/compactors", "/api/compactors/C1", "/api/compactors/C1/readings", "/api/alerts", "/api/pickups",
                 "/api/cockpit/actions", "/api/models/performance", "/api/admin/tenants", "/api/auth/me"):
        assert app_client.get(path).status_code == 401, path


def test_health_and_portal_stay_open(app_client):
    assert app_client.get("/api/health").status_code == 200
    assert app_client.get("/portal").status_code == 200


def test_admin_sees_all_customers(world):
    c, admin, _, _ = world
    assert {"C1", "C2", "C3", "X1", "Y1"} <= {s["compactor_id"] for s in c.get("/api/compactors", headers=admin).json()}
    assert {"X1", "Y1"} <= {a["compactor_id"] for a in c.get("/api/alerts", headers=admin).json()}


def test_customer_sees_only_own_devices(world):
    c, _, a, b = world
    assert [s["compactor_id"] for s in c.get("/api/compactors", headers=a).json()] == ["X1"]
    assert [s["compactor_id"] for s in c.get("/api/compactors", headers=b).json()] == ["Y1"]
    assert {x["compactor_id"] for x in c.get("/api/alerts", headers=a).json()} == {"X1"}
    assert len(c.get("/api/compactors/X1/readings", headers=a).json()) == 2


@pytest.mark.parametrize("path", ["/api/compactors/{}", "/api/compactors/{}/readings", "/api/alerts?compactor_id={}"])
def test_cross_tenant_access_is_404_and_same_as_unknown_device(world, path):
    c, _, a, b = world
    assert c.get(path.format("Y1"), headers=a).status_code == 404
    assert c.get(path.format("X1"), headers=b).status_code == 404
    assert c.get(path.format("C1"), headers=a).status_code == 404   # no owner = admin only
    assert c.get(path.format("Y1"), headers=a).json() == {"detail": "Unknown compactor 'Y1'"}


def test_pickups_are_scoped(world):
    c, _, a, _ = world
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.pickups).values(compactor_id="Y1", status="done", kind="manual"))
        conn.execute(insert(db.pickups).values(compactor_id="X1", status="done", kind="manual"))
    assert {p["compactor_id"] for p in c.get("/api/pickups", headers=a).json()} == {"X1"}



def test_customer_rates_only_own_lifts(world):
    """Ratings: a customer sees and rates only their own lifts; another customer's lift answers 404."""
    c, _, a, _ = world
    with db.get_engine().begin() as conn:
        mine = conn.execute(insert(db.pickups).values(compactor_id="X1", status="done", kind="manual")).inserted_primary_key[0]
        other = conn.execute(insert(db.pickups).values(compactor_id="Y1", status="done", kind="manual")).inserted_primary_key[0]
    assert [p["id"] for p in c.get("/api/pickups/ratings", headers=a).json()] == [mine]
    r = c.put(f"/api/pickups/{mine}/rating", headers=a, json={"truck_on_time": True})
    assert r.status_code == 200 and r.json()["rated_by"] == "a@one.example"
    assert c.put(f"/api/pickups/{other}/rating", headers=a, json={"truck_on_time": False}).status_code == 404
    assert c.get("/api/pickups/ratings").status_code == 401

def test_customer_cannot_use_admin_or_analysis_endpoints(world):
    c, _, a, _ = world
    for method, path in (("get", "/api/admin/tenants"), ("get", "/api/admin/registrations"), ("get", "/api/cockpit/actions"),
                         ("get", "/api/models/performance")):
        assert getattr(c, method)(path, headers=a).status_code == 403, path
    assert c.post("/api/admin/tenants/1/devices", headers=a, json={"compactor_id": "Y1"}).status_code == 403


def test_customer_cannot_write_readings_or_feedback_without_the_machine_key(world):
    c, _, a, _ = world
    assert c.post("/api/readings", headers=a, json={"compactor_id": "Y1", "weight_kg": 1}).status_code == 401
    assert c.post("/api/alerts/1/feedback", headers=a, json={"verdict": "CORRECT", "decided_by": "x"}).status_code == 403


def test_registration_gives_no_access_even_with_an_existing_company_name(world):
    c, admin, _, _ = world
    r = c.post("/api/auth/register", json={"email": "evil@x.example", "password": PW, "company": "Customer One"})
    assert r.status_code == 202
    r = c.post("/api/auth/login", json={"email": "evil@x.example", "password": PW})
    assert r.status_code == 403
    with db.get_engine().connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.email == "evil@x.example")).mappings().first()
    assert u["tenant_id"] is None and u["status"] == "pending" and u["role"] == "customer"


def test_registration_ignores_extra_fields(app_client):
    c = app_client
    c.post("/api/auth/register", json={"email": "x@x.example", "password": PW, "company": "Co", "role": "admin", "status": "active", "tenant_id": 1})
    with db.get_engine().connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.email == "x@x.example")).mappings().first()
    assert (u["role"], u["status"], u["tenant_id"]) == ("customer", "pending", None)


def test_registering_an_existing_email_changes_nothing_and_reveals_nothing(world):
    c, _, _, _ = world
    new = c.post("/api/auth/register", json={"email": "fresh@x.example", "password": PW, "company": "Co"})
    taken = c.post("/api/auth/register", json={"email": "a@one.example", "password": "another-password-1", "company": "Co"})
    assert (new.status_code, new.json()) == (taken.status_code, taken.json())
    sign_in(c, "a@one.example")   # the old password still works


def test_rejected_user_cannot_sign_in(app_client):
    c = app_client
    admin = sign_in(c, *ADMIN)
    c.post("/api/auth/register", json={"email": "r@x.example", "password": PW, "company": "Co"})
    uid = c.get("/api/admin/registrations", headers=admin).json()[0]["id"]
    assert c.post(f"/api/admin/registrations/{uid}/reject", headers=admin).status_code == 200
    assert c.post("/api/auth/login", json={"email": "r@x.example", "password": PW}).status_code == 401


def test_device_cannot_have_two_owners(world):
    c, admin, _, _ = world
    tenants = c.get("/api/admin/tenants", headers=admin).json()
    two = next(t for t in tenants if t["name"] == "Customer Two")
    assert c.post(f"/api/admin/tenants/{two['id']}/devices", headers=admin, json={"compactor_id": "X1"}).status_code == 409


def test_refused_approval_leaves_no_half_made_customer(world, fake):
    c, admin, _, _ = world
    c.post("/api/auth/register", json={"email": "n@x.example", "password": PW, "company": "Co"})
    uid = c.get("/api/admin/registrations", headers=admin).json()[0]["id"]
    before = fake.next_org
    r = c.post(f"/api/admin/registrations/{uid}/approve", headers=admin, json={"new_tenant_name": "Greedy", "device_ids": ["X1"]})
    assert r.status_code == 409 and fake.next_org == before


def test_failed_grafana_setup_rolls_back(app_client, fake):
    c = app_client
    admin = sign_in(c, *ADMIN)
    fake.fail = "datasource"
    assert c.post("/api/admin/tenants", headers=admin, json={"name": "Broken Co"}).status_code == 502
    assert fake.orgs_deleted and c.get("/api/admin/tenants", headers=admin).json() == []


def test_a_grafana_account_we_did_not_create_is_never_adopted(app_client, fake):
    """Registering as the Grafana admin's e-mail must not reset that admin's password."""
    c = app_client
    admin = sign_in(c, *ADMIN)
    fake.existing["admin@localhost.example"] = {"id": 1, "isGrafanaAdmin": True}
    onboard(c, admin, "admin@localhost.example", "Sneaky", [])
    r = c.post("/api/auth/login", json={"email": "admin@localhost.example", "password": PW})
    assert r.status_code == 200 and r.json()["grafana_ready"] is False and fake.created == []


def test_suspended_customer_loses_access_at_once(world):
    c, admin, a, _ = world
    tid = next(t["id"] for t in c.get("/api/admin/tenants", headers=admin).json() if t["name"] == "Customer One")
    assert c.post(f"/api/admin/tenants/{tid}/status", headers=admin, json={"status": "suspended"}).status_code == 200
    assert c.get("/api/compactors", headers=a).status_code == 401
    assert c.post("/api/auth/login", json={"email": "a@one.example", "password": PW}).status_code == 403


@pytest.mark.parametrize("env,value,text", [("INGEST_API_KEY", "", "INGEST_API_KEY"), ("GRAFANA_ADMIN_PASSWORD", "admin", "GRAFANA_PASS")])
def test_customers_are_refused_on_a_weak_server(app_client, monkeypatch, env, value, text):
    c = app_client
    admin = sign_in(c, *ADMIN)
    monkeypatch.setenv(env, value)
    r = c.post("/api/admin/tenants", headers=admin, json={"name": "Too Early"})
    assert r.status_code == 503 and text in r.json()["detail"]


def test_customers_are_refused_while_grafana_is_anonymous(app_client, fake):
    c = app_client
    admin = sign_in(c, *ADMIN)
    fake.anonymous_is_off = lambda: False
    assert c.post("/api/admin/tenants", headers=admin, json={"name": "Too Early"}).status_code == 503


def test_login_locks_after_repeated_failures(world):
    c = world[0]
    for _ in range(auth.MAX_FAILED):
        assert c.post("/api/auth/login", json={"email": "a@one.example", "password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "a@one.example", "password": PW}).status_code == 401


def test_logout_ends_the_session(world):
    c, _, a, _ = world
    assert c.post("/api/auth/logout", headers=a).status_code == 200
    assert c.get("/api/compactors", headers=a).status_code == 401


def test_session_cookie_is_httponly_and_only_a_hash_is_stored(app_client):
    c = app_client
    r = c.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    with db.get_engine().connect() as conn:
        assert r.json()["token"] not in [x[0] for x in conn.execute(select(db.auth_sessions.c.token_hash))]


def test_password_hash_round_trip():
    h = auth.hash_password("something-long")
    assert h.startswith("scrypt$") and "something-long" not in h
    assert auth.verify_password("something-long", h) and not auth.verify_password("nope", h)
    assert not auth.verify_password("x", "!")


def test_customer_dashboards_only_use_the_tenant_views():
    """Second line of defence: customer pages must never name a base table or the admin datasource."""
    files = sorted((Path(provision.__file__).parent / "tenant_dashboards").glob("*.json"))
    assert len(files) == 7
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "compactor-pg" not in text
        for panel in json.loads(text)["panels"]:
            for target in panel.get("targets", []):
                for table in re.findall(r"(?:FROM|JOIN)\s+([a-z_.]+)", target["rawSql"]):
                    assert table.startswith("tenant_api."), (f.name, table)


@pytest.fixture()
def cockpit_action(world):
    from sqlalchemy import text
    with db.get_engine().begin() as conn:
        conn.execute(text("CREATE TABLE cp_actions (action_id TEXT, action TEXT, device_id TEXT, flagged_invoice_eur REAL)"))
        conn.execute(text("INSERT INTO cp_actions VALUES ('ACT-1', 'DISPUTE_INVOICE', 'CMP-1', 10)"))
    return world


DECISION = "/api/cockpit/actions/ACT-1/decision"


def stored_decisions():
    with db.get_engine().connect() as conn:
        return conn.execute(select(db.action_decisions.c.decided_by)).scalars().all()


def test_only_a_signed_in_admin_can_decide(cockpit_action):
    c, _, a, _ = cockpit_action
    body = {"decision": "APPROVE"}
    assert c.post(DECISION, json=body).status_code == 401
    assert c.post(DECISION, json=body, headers={"X-API-Key": "machine-key"}).status_code == 401
    assert c.post(DECISION, json=body, headers=a).status_code == 403
    assert c.post(DECISION, json=body, headers={**a, "X-API-Key": "machine-key"}).status_code == 403
    assert stored_decisions() == []


def test_decision_log_names_the_admin_not_the_typed_name(cockpit_action):
    c, admin, _, _ = cockpit_action
    r = c.post(DECISION, headers=admin, json={"decision": "APPROVE", "decided_by": "Someone Else"})
    assert r.status_code == 200 and r.json()["decided_by"] == ADMIN[0]
    assert stored_decisions() == [ADMIN[0]]
