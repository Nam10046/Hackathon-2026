"""Set up a customer: Postgres role + Grafana org, datasource, folder, dashboards. Owner: backend person.

Nothing per customer is edited by hand: every org gets the same files from app/tenant_dashboards, and they all use the
datasource uid "tenant-pg". What differs is the Postgres role behind that datasource.
"""
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app import grafana
from app.db import compactors, get_engine, tenant_devices, tenants, users

TEMPLATES = Path(__file__).parent / "tenant_dashboards"
FOLDER_UID, DATASOURCE_UID, HOME_UID = "cust-pages", "tenant-pg", "cust-overview"
ROLE_RE = re.compile(r"^t_[0-9a-f]{16}$")


class NotSafe(RuntimeError):
    """The server is not configured safely enough to hold customers."""


def security_problems() -> list[str]:
    """Each of these would let one customer reach another's data, so customers are refused until they are fixed."""
    problems = []
    if os.getenv("GRAFANA_ADMIN_PASSWORD", "") in ("", "admin"):
        problems.append("GRAFANA_PASS is empty or 'admin'")
    if not os.getenv("INGEST_API_KEY", ""):
        problems.append("INGEST_API_KEY is empty: anyone could post readings for any device")
    try:
        if not grafana.client().anonymous_is_off():
            problems.append("Grafana allows anonymous access")
    except httpx.HTTPError:
        problems.append("Grafana cannot be reached")
    return problems


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "customer"


def _create_db_role() -> tuple[str | None, str | None]:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return None, None
    role, password = "t_" + secrets.token_hex(8), secrets.token_hex(24)   # only [a-z0-9_]: safe inside the statement
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT "
                             f"CONNECTION LIMIT 10 PASSWORD '{password}'")
        conn.exec_driver_sql(f"ALTER ROLE {role} SET search_path = tenant_api")
        conn.exec_driver_sql(f"ALTER ROLE {role} SET default_transaction_read_only = on")
        conn.exec_driver_sql(f"ALTER ROLE {role} SET statement_timeout = '15s'")   # one customer cannot stall the others
        # SET FALSE (PostgreSQL 16+): it gets the rights, but cannot SET ROLE and break its own pooled connections
        conn.exec_driver_sql(f"GRANT tenant_reader TO {role} WITH INHERIT TRUE, SET FALSE")
    return role, password


def _drop_db_role(role):
    if role and ROLE_RE.match(role):
        with get_engine().begin() as conn:
            conn.exec_driver_sql(f"DROP ROLE IF EXISTS {role}")


def _datasource(role, password) -> dict:
    url = get_engine().url
    return {"name": "Compactor data", "uid": DATASOURCE_UID, "type": "grafana-postgresql-datasource", "access": "proxy",
            "url": f"{url.host}:{url.port or 5432}", "user": role or "none", "isDefault": True,
            "secureJsonData": {"password": password or "none"},
            "jsonData": {"database": url.database, "sslmode": url.query.get("sslmode", "disable"), "postgresVersion": 1600,
                         "timescaledb": False, "maxOpenConns": 5}}


def push_dashboards(org_id):
    """Also safe to re-run for an existing customer, to roll out changed dashboards."""
    g = grafana.client()
    g.ensure_folder(org_id, FOLDER_UID, "Smart Compactor")
    for f in sorted(TEMPLATES.glob("*.json")):
        g.save_dashboard(org_id, json.loads(f.read_text(encoding="utf-8")), FOLDER_UID)
    g.set_home(org_id, HOME_UID)


def provision_tenant(name: str) -> dict:
    """Creates everything or nothing."""
    problems = security_problems()
    if problems:
        raise NotSafe("; ".join(problems))
    name = name.strip()
    slug = _slug(name)
    with get_engine().connect() as conn:
        if conn.execute(select(tenants.c.id).where((tenants.c.slug == slug) | (tenants.c.name == name))).first():
            raise ValueError(f"A customer called '{name}' already exists")
    g = grafana.client()
    role, password = _create_db_role()
    org_id = None
    try:
        org_id = g.create_org(name)
        g.upsert_datasource(org_id, _datasource(role, password))
        push_dashboards(org_id)
        with get_engine().begin() as conn:
            tid = conn.execute(insert(tenants).values(
                slug=slug, name=name, status="active", db_role=role, grafana_org_id=org_id,
                created_at=datetime.now(timezone.utc))).inserted_primary_key[0]
    except Exception:
        if org_id:
            g.delete_org(org_id)
        _drop_db_role(role)
        raise
    return {"id": tid, "slug": slug, "name": name, "grafana_org_id": org_id}


def assign_device(tenant_id: int, compactor_id: str, by: str):
    with get_engine().begin() as conn:
        owner = conn.execute(select(tenant_devices.c.tenant_id).where(tenant_devices.c.compactor_id == compactor_id)).scalar()
        if owner is not None and owner != tenant_id:
            raise ValueError(f"Device '{compactor_id}' already belongs to another customer")
        if owner is None:
            try:
                conn.execute(insert(tenant_devices).values(compactor_id=compactor_id, tenant_id=tenant_id,
                                                           assigned_at=datetime.now(timezone.utc), assigned_by=by))
            except IntegrityError:
                raise ValueError(f"Device '{compactor_id}' does not exist or was just assigned")
        # the admin's Analysis pages show the owner by name (access itself is decided by tenant_devices)
        name = conn.execute(select(tenants.c.name).where(tenants.c.id == tenant_id)).scalar()
        conn.execute(update(compactors).where(compactors.c.id == compactor_id).values(customer_name=name))


def ensure_grafana_user(user: dict, password: str) -> bool:
    """First sign-in of an approved customer: make the Grafana account with the same password.
    Returns False if Grafana could not be updated; the portal still works and the next sign-in tries again."""
    if user.get("tenant_id") is None:
        return False
    with get_engine().connect() as conn:
        org_id = conn.execute(select(tenants.c.grafana_org_id).where(tenants.c.id == user["tenant_id"])).scalar()
    if org_id is None:
        return False
    g = grafana.client()
    try:
        gid = user.get("grafana_user_id")
        if gid is None:
            if g.find_user(user["email"]) is not None:
                # never adopt an account we did not create: it could be the Grafana admin or someone else's
                print(f"user {user['id']}: a Grafana account with this e-mail already exists, not touching it", flush=True)
                return False
            gid = g.create_user(user["email"], password, org_id)
            with get_engine().begin() as conn:
                conn.execute(update(users).where(users.c.id == user["id"]).values(grafana_user_id=gid))
        g.only_in_org(gid, user["email"], org_id)
        return True
    except (grafana.GrafanaError, httpx.HTTPError) as e:
        print(f"user {user['id']}: Grafana sync failed: {e}", flush=True)
        return False


def set_tenant_status(tenant_id: int, status: str):
    """Suspended: the views return nothing at once, the database role cannot log in, Grafana accounts are locked."""
    with get_engine().begin() as conn:
        t = conn.execute(select(tenants).where(tenants.c.id == tenant_id)).mappings().first()
        if t is None:
            raise KeyError(tenant_id)
        conn.execute(update(tenants).where(tenants.c.id == tenant_id).values(status=status))
        members = conn.execute(select(users.c.grafana_user_id).where(
            users.c.tenant_id == tenant_id, users.c.grafana_user_id.is_not(None))).scalars().all()
        if t["db_role"] and ROLE_RE.match(t["db_role"]):
            conn.exec_driver_sql(f"ALTER ROLE {t['db_role']} {'LOGIN' if status == 'active' else 'NOLOGIN'}")
    g = grafana.client()
    for gid in members:
        g.set_disabled(gid, status != "active")
