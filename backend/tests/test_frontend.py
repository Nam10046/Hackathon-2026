"""Frontend contract: mock files stay dev-only, and fixtures keep the shape of the real API."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text

from app import auth, db, grafana
from app.schemas import Alert, Status
from tests.test_tenancy import ADMIN, FakeGrafana, onboard, sign_in

STATIC = Path(auth.__file__).parent / "static"
FX = json.loads((STATIC / "dev" / "fixtures.json").read_text(encoding="utf-8"))


def scenario(name):
    return {**FX["defaults"], **FX["scenarios"][name]}


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN[1])
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "strong-grafana-pass")
    monkeypatch.setenv("INGEST_API_KEY", "machine-key")
    monkeypatch.delenv("FRONTEND_MOCK", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setattr(grafana, "client", FakeGrafana)
    fake = FakeGrafana()
    monkeypatch.setattr(grafana, "client", lambda: fake)
    db.reset_engine()
    from app.main import app
    with TestClient(app) as client:
        yield client
    db.reset_engine()


def test_pages_and_design_files_load_without_login(c):
    for path in ("/portal", "/cockpit", "/assets/ui.css", "/assets/ui.js", "/assets/data.js", "/assets/portal.js", "/assets/cockpit.js"):
        assert c.get(path).status_code == 200, path


def test_pages_contain_no_data_and_do_not_load_mock_code(c):
    for path in ("/portal", "/cockpit"):
        html = c.get(path).text
        assert "/dev/" not in html and "fixtures" not in html and "Mock" not in html


@pytest.mark.parametrize("name", ["mock.js", "fixtures.json"])
def test_mock_files_are_off_by_default(c, name):
    assert c.get(f"/dev/{name}").status_code == 404


def test_mock_files_need_the_server_flag(c, monkeypatch):
    monkeypatch.setenv("FRONTEND_MOCK", "true")
    assert c.get("/dev/mock.js").status_code == 200
    assert c.head("/dev/mock.js").status_code == 200
    assert c.get("/dev/fixtures.json").json()["scenarios"]


def test_mock_is_never_served_on_https_deployments(c, monkeypatch):
    monkeypatch.setenv("FRONTEND_MOCK", "true")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    assert c.get("/dev/mock.js").status_code == 404


@pytest.mark.parametrize("path", ["/dev/portal.html", "/dev/..%2fdb.py", "/dev/%2e%2e%2fportal.html", "/assets/..%2f..%2fdb.py", "/assets/../db.py"])
def test_no_other_file_can_be_reached(c, monkeypatch, path):
    monkeypatch.setenv("FRONTEND_MOCK", "true")
    r = c.get(path)
    assert r.status_code == 404 or "metadata" not in r.text


def test_assets_folder_holds_only_design_files():
    assert {f.suffix for f in (STATIC / "assets").iterdir()} <= {".css", ".js"}


def test_fixture_devices_and_alerts_match_the_api_schemas():
    for name in FX["scenarios"]:
        s = scenario(name)
        for device in s["compactors"]:
            Status(**device)
            assert set(device) == set(Status.model_fields)
        for alert in s["alerts"]:
            Alert(**alert)


def test_fixtures_are_marked_as_made_up():
    s = scenario("device-connected")
    assert all(d["compactor_id"].startswith("M-") and "Mock" in d["name"] for d in s["compactors"])
    assert all(a["message"].startswith("Simulated demo:") for a in s["alerts"])
    assert all("MOCK TEXT" in a["rationale"] for a in scenario("cockpit-pending")["actions"])


def keys(rows):
    assert rows, "the API returned nothing to compare with"
    return set(rows[0])


def test_fixture_keys_match_what_the_real_api_returns(c):
    admin = sign_in(c, *ADMIN)
    onboard(c, admin, "a@one.example", "Customer One", ["C1"])
    c.post("/api/auth/register", json={"email": "w@x.example", "password": "a-long-password-1", "company": "Co"})
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.pickups).values(compactor_id="C1", status="done", kind="manual"))
    customer = sign_in(c, "a@one.example", "correct-horse-battery")
    d = FX["defaults"]
    assert keys(c.get("/api/pickups", headers=customer).json()) == set(d["pickups"][0])
    assert set(c.get("/api/auth/me", headers=customer).json()) == set(d["me"])
    assert keys(c.get("/api/admin/registrations", headers=admin).json()) == set(d["registrations"][0])
    assert keys(c.get("/api/admin/tenants", headers=admin).json()) == set(d["tenants"][0])
    assert keys(c.get("/api/admin/devices", headers=admin).json()) == set(d["devices"][0])


def test_fixture_actions_match_the_cockpit_query(c):
    cols = [k for k in FX["defaults"]["actions"][0] if k not in ("status", "decision", "decided_by", "decision_note", "decided_at")]
    with db.get_engine().begin() as conn:
        conn.execute(text(f"CREATE TABLE cp_actions ({', '.join(cols)})"))
        conn.execute(text(f"INSERT INTO cp_actions ({', '.join(cols)}) VALUES ({', '.join(':' + x for x in cols)})"),
                     {k: FX["defaults"]["actions"][0][k] for k in cols})
        conn.execute(text("CREATE TABLE cp_flags (entity_type, entity_id, label_family, found_at, device_id, explanation, evidence, "
                          "eur_at_stake, evidence_tag, calculation, likely_cause)"))
    admin = sign_in(c, *ADMIN)
    rows = c.get("/api/cockpit/actions", headers=admin).json()
    assert keys(rows) == set(FX["defaults"]["actions"][0])
    ev = c.get(f"/api/cockpit/actions/{rows[0]['action_id']}/evidence", headers=admin).json()
    assert {"findings", "decision_history"} <= set(ev)
