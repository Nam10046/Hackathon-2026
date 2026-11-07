"""Who is asking? Taken ONLY from the login session (app/auth.py), never from headers the client sends.

Admin sees every customer. A customer sees exactly the compactors an admin assigned to their tenant (tenant_devices)
and the invoices entered for that tenant. Headers like X-User-Role / X-Customer are ignored on purpose: anyone can
send them."""
from dataclasses import dataclass, field

from fastapi import Depends
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
