"""Who is asking? Taken ONLY from the login session (app/auth.py), never from headers the client sends.

Admin sees every customer. A customer sees exactly the compactors an admin assigned to their tenant (tenant_devices)
and the invoices entered for that tenant. Headers like X-User-Role / X-Customer are ignored on purpose: anyone can
send them."""
import hashlib
import os
import time
from dataclasses import dataclass, field

import httpx
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select

from app.auth import allowed_devices, current_user
from app.db import get_engine, tenants


@dataclass
class Viewer:
    role: str                                   # "admin" or "customer"
    customer: str | None = None                 # the tenant's name, for customers
    devices: set[str] | None = field(default=None)   # compactors this viewer may see; None = all (admin)
    email: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana:3000").rstrip("/")
GRAFANA_COOKIE = os.getenv("GRAFANA_SESSION_COOKIE", "grafana_session")
ADMIN_ORG = 1                                   # Grafana org 1 = the admin's org (every customer has an org of its own)
_seen: dict[str, tuple[float, dict | None]] = {}   # cookie hash -> (checked at, Grafana user), so a 5 s refresh asks Grafana once per 30 s


def _grafana_user(session: str) -> dict | None:
    """Ask Grafana who this session belongs to (None = not a valid Grafana login)."""
    try:
        r = httpx.get(GRAFANA_URL + "/api/user", cookies={GRAFANA_COOKIE: session}, timeout=5)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def grafana_admin(request: Request) -> Viewer | None:
    """Signed in to Grafana in the admin org? Browsers share cookies across ports, so the Grafana login cookie also
    reaches this backend; Grafana itself says whether it is valid. Customers are in their own orgs: never admin here."""
    session = request.cookies.get(GRAFANA_COOKIE)
    if not session:
        return None
    key = hashlib.sha256(session.encode()).hexdigest()
    at, user = _seen.get(key, (0.0, None))
    if time.monotonic() - at > 30:
        user = _grafana_user(session)
        _seen[key] = (time.monotonic(), user)
    if user and user.get("orgId") == ADMIN_ORG:
        return Viewer("admin", email=f"{user.get('login') or user.get('email')} (Grafana)")
    return None


def portal_or_grafana(request: Request, authorization: str | None = Header(default=None)) -> Viewer:
    """For the Book truck panel inside Grafana: the Portal login, or else the Grafana login (admin org)."""
    try:
        return who_is_asking(current_user(request, authorization))
    except HTTPException as e:
        if e.status_code != 401:
            raise
        viewer = grafana_admin(request)
        if viewer is None:
            raise
        return viewer


def who_is_asking(user: dict = Depends(current_user)) -> Viewer:
    if user["role"] == "admin":
        return Viewer("admin", email=user.get("email"))
    name = None
    if user.get("tenant_id") is not None:
        with get_engine().connect() as conn:
            name = conn.execute(select(tenants.c.name).where(tenants.c.id == user["tenant_id"])).scalar()
    # a customer without a tenant gets a name nobody has and no devices: sees nothing
    return Viewer("customer", customer=name or f"(no customer: user {user.get('id')})",
                  devices=allowed_devices(user), email=user.get("email"))
