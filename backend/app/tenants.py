"""Admin onboarding: approve registrations, create customers, hand out devices. Owner: backend person.

A registration proves nothing about who someone is. Tenant and devices are decided here, by an admin, never by the user.
"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app import grafana, provision
from app.auth import require_admin
from app.db import auth_sessions, compactors, get_engine, materials, tenant_devices, tenants, users

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class ApproveIn(BaseModel):
    tenant_id: int | None = None           # join an existing customer ...
    new_tenant_name: str | None = Field(default=None, min_length=2, max_length=120)   # ... or create a new one
    device_ids: list[str] = []


class DeviceIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")      # also the MQTT topic level, so no / + #
    name: str = Field(min_length=1, max_length=120)
    material: str
    capacity_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)
    on_call_threshold_pct: float | None = Field(default=80, ge=1, le=100)


class AssignIn(BaseModel):
    compactor_id: str


class StatusIn(BaseModel):
    status: Literal["active", "suspended"]


def _tenant_or_404(conn, tenant_id):
    t = conn.execute(select(tenants).where(tenants.c.id == tenant_id)).mappings().first()
    if t is None:
        raise HTTPException(404, "Unknown customer")
    return t


def _provision(name):
    try:
        return provision.provision_tenant(name)
    except provision.NotSafe as e:
        raise HTTPException(503, f"Fix the server settings first: {e}")
    except ValueError as e:
        raise HTTPException(409, str(e))
    except grafana.GrafanaError as e:
        raise HTTPException(502, f"Grafana refused the setup: {e}")


@router.get("/registrations")
def registrations(status: str = "pending"):
    with get_engine().connect() as conn:
        rows = conn.execute(select(users.c.id, users.c.email, users.c.company_requested, users.c.status, users.c.created_at)
                            .where(users.c.status == status, users.c.role == "customer").order_by(users.c.id)).mappings()
        return [dict(r) for r in rows]


@router.post("/registrations/{user_id}/approve")
def approve(user_id: int, body: ApproveIn, admin: dict = Depends(require_admin)):
    if (body.tenant_id is None) == (body.new_tenant_name is None):
        raise HTTPException(422, "Give either tenant_id or new_tenant_name")
    with get_engine().connect() as conn:
        u = conn.execute(select(users).where(users.c.id == user_id, users.c.role == "customer")).mappings().first()
        if u is None or u["status"] != "pending":
            raise HTTPException(404, "No pending registration with this id")
        if body.tenant_id is not None:
            _tenant_or_404(conn, body.tenant_id)
        # check the devices first, so a refused approval leaves no half-made customer behind
        for cid in body.device_ids:
            if conn.execute(select(compactors.c.id).where(compactors.c.id == cid)).first() is None:
                raise HTTPException(404, f"Unknown compactor '{cid}'")
            owner = conn.execute(select(tenant_devices.c.tenant_id).where(tenant_devices.c.compactor_id == cid)).scalar()
            if owner is not None and owner != body.tenant_id:
                raise HTTPException(409, f"Device '{cid}' already belongs to another customer")
    if body.tenant_id is None:
        tenant_id = _provision(body.new_tenant_name)["id"]
    else:
        problems = provision.security_problems()
        if problems:
            raise HTTPException(503, "Fix the server settings first: " + "; ".join(problems))
        tenant_id = body.tenant_id
    for cid in body.device_ids:
        try:
            provision.assign_device(tenant_id, cid, admin["email"])
        except ValueError as e:
            raise HTTPException(409, str(e))
    with get_engine().begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(
            status="active", tenant_id=tenant_id, decided_by=admin["email"], decided_at=datetime.now(timezone.utc)))
    return {"user_id": user_id, "status": "active", "tenant_id": tenant_id}


@router.post("/registrations/{user_id}/reject")
def reject(user_id: int, admin: dict = Depends(require_admin)):
    with get_engine().begin() as conn:
        n = conn.execute(update(users).where(users.c.id == user_id, users.c.status == "pending", users.c.role == "customer")
                         .values(status="rejected", password_hash="!", decided_by=admin["email"],
                                 decided_at=datetime.now(timezone.utc))).rowcount
    if not n:
        raise HTTPException(404, "No pending registration with this id")
    return {"user_id": user_id, "status": "rejected"}


@router.get("/tenants")
def list_tenants():
    with get_engine().connect() as conn:
        out = [dict(r) for r in conn.execute(select(tenants.c.id, tenants.c.slug, tenants.c.name, tenants.c.status,
                                                    tenants.c.grafana_org_id).order_by(tenants.c.id)).mappings()]
        for t in out:
            t["devices"] = sorted(conn.execute(select(tenant_devices.c.compactor_id)
                                               .where(tenant_devices.c.tenant_id == t["id"])).scalars())
            t["users"] = conn.execute(select(func.count()).select_from(users).where(users.c.tenant_id == t["id"])).scalar()
    return out


class TenantIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantIn):
    return _provision(body.name)


@router.post("/tenants/{tenant_id}/status")
def tenant_status(tenant_id: int, body: StatusIn):
    try:
        provision.set_tenant_status(tenant_id, body.status)
    except KeyError:
        raise HTTPException(404, "Unknown customer")
    if body.status != "active":
        with get_engine().begin() as conn:
            members = select(users.c.id).where(users.c.tenant_id == tenant_id)
            conn.execute(delete(auth_sessions).where(auth_sessions.c.user_id.in_(members)))
    return {"id": tenant_id, "status": body.status}


@router.get("/devices")
def list_devices():
    q = (select(compactors.c.id, compactors.c.name, compactors.c.material, tenants.c.id.label("tenant_id"),
                tenants.c.name.label("tenant"))
         .select_from(compactors.outerjoin(tenant_devices, tenant_devices.c.compactor_id == compactors.c.id)
                      .outerjoin(tenants, tenants.c.id == tenant_devices.c.tenant_id)).order_by(compactors.c.id))
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


@router.post("/devices", status_code=201)
def create_device(body: DeviceIn):
    try:
        with get_engine().begin() as conn:
            if conn.execute(select(materials.c.name).where(materials.c.name == body.material)).first() is None:
                raise HTTPException(422, f"Unknown material '{body.material}'")
            conn.execute(insert(compactors).values(**body.model_dump()))
    except IntegrityError:
        raise HTTPException(409, f"Device '{body.id}' already exists")
    return body.model_dump()


@router.post("/tenants/{tenant_id}/devices")
def assign(tenant_id: int, body: AssignIn, admin: dict = Depends(require_admin)):
    with get_engine().connect() as conn:
        _tenant_or_404(conn, tenant_id)
        if conn.execute(select(compactors.c.id).where(compactors.c.id == body.compactor_id)).first() is None:
            raise HTTPException(404, f"Unknown compactor '{body.compactor_id}'")
    try:
        provision.assign_device(tenant_id, body.compactor_id, admin["email"])
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"tenant_id": tenant_id, "compactor_id": body.compactor_id}


@router.delete("/tenants/{tenant_id}/devices/{compactor_id}")
def unassign(tenant_id: int, compactor_id: str):
    with get_engine().begin() as conn:
        n = conn.execute(delete(tenant_devices).where(tenant_devices.c.tenant_id == tenant_id,
                                                      tenant_devices.c.compactor_id == compactor_id)).rowcount
    if not n:
        raise HTTPException(404, "This customer does not own that device")
    return {"tenant_id": tenant_id, "compactor_id": compactor_id, "removed": True}
