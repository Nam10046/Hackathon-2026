"""Who is asking? Admin sees all customers, a customer user sees only their own data (Analysis API).

PLACEHOLDER until the user platform (teammate) is merged. That platform logs the user in, then calls this API
server-to-server with:
    X-User-Role: admin | customer
    X-Customer:  <customer_name>          (required for role "customer")
and, when ADMIN_API_KEY is set on the server, admins also send X-API-Key: <ADMIN_API_KEY>.
Never let a browser set these headers directly: the platform must check the login first.
No headers at all = admin, but only while ADMIN_API_KEY is empty (laptop / Grafana demo)."""
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException


@dataclass
class Viewer:
    role: str                    # "admin" or "customer"
    customer: str | None = None  # set for customers

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def who_is_asking(x_user_role: str | None = Header(default=None), x_customer: str | None = Header(default=None),
                  x_api_key: str | None = Header(default=None)) -> Viewer:
    role = (x_user_role or "admin").lower()
    if role == "customer":
        if not x_customer:
            raise HTTPException(400, "X-Customer is required for role 'customer'")
        return Viewer("customer", x_customer)
    if role != "admin":
        raise HTTPException(400, "X-User-Role must be 'admin' or 'customer'")
    key = os.getenv("ADMIN_API_KEY", "")
    if key and x_api_key != key:
        raise HTTPException(401, "Admin access needs X-API-Key")
    return Viewer("admin")
