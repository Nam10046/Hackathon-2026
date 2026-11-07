"""Login, sessions and "who may see what". Owner: backend person.

Passwords: scrypt (standard library). Sessions: random token, only its SHA-256 is stored, so logout and suspension
work at once. The token travels in an HttpOnly cookie (portal) or as "Authorization: Bearer <token>" (scripts).
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update

from app.db import auth_sessions, get_engine, tenant_devices, tenants, users

router = APIRouter()
COOKIE = "sc_session"
SESSION_HOURS = 12
MAX_FAILED = 5
LOCK_MINUTES = 5
MAX_PENDING = 200                  # registrations waiting for an admin; stops anyone filling the table
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
N, R, P = 2 ** 15, 8, 1
SYSTEM_ADMIN = {"id": 0, "email": "auth-disabled", "role": "admin", "status": "active", "tenant_id": None}


def enforced() -> bool:
    """On unless switched off on purpose. Only the older contract tests switch it off."""
    return os.getenv("AUTH_ENFORCE", "true").lower() != "false"


def _now():
    return datetime.now(timezone.utc)


def _utc(t):
    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


def _scrypt(password: str, salt: bytes, n=N, r=R, p=P) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${N}${R}${P}${salt.hex()}${_scrypt(password, salt).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p)).hex(), digest)
    except ValueError:             # "!" = account that can never log in
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(16))   # unknown e-mail costs the same time as a wrong password


def ensure_admin():
    """First platform admin comes from the environment. Nobody can register as admin."""
    email = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@compactor.local").strip().lower()
    password = os.getenv("PLATFORM_ADMIN_PASSWORD", "")
    if len(password) < 12:
        print("PLATFORM_ADMIN_PASSWORD is not set (12+ characters): no admin login. Run scripts/init_env.py", flush=True)
        return
    with get_engine().begin() as conn:
        if conn.execute(select(users.c.id).where(users.c.email == email)).first() is None:
            conn.execute(insert(users).values(email=email, password_hash=hash_password(password), role="admin",
                                              status="active", failed_logins=0, created_at=_now()))


def _token_from(request: Request, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(COOKIE)


def current_user(request: Request, authorization: str | None = Header(default=None)) -> dict:
    if not enforced():
        return SYSTEM_ADMIN
    token = _token_from(request, authorization)
    if not token:
        raise HTTPException(401, "Sign in first")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_engine().connect() as conn:
        row = conn.execute(
            select(users, auth_sessions.c.expires_at, tenants.c.status.label("tenant_status"))
            .join(auth_sessions, auth_sessions.c.user_id == users.c.id)
            .outerjoin(tenants, tenants.c.id == users.c.tenant_id)
            .where(auth_sessions.c.token_hash == digest)).mappings().first()
    if row is None or _utc(row["expires_at"]) < _now() or row["status"] != "active":
        raise HTTPException(401, "Sign in first")
    if row["role"] != "admin" and row["tenant_status"] != "active":
        raise HTTPException(403, "This customer account is suspended")
    return dict(row)


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admins only")
    return user


def allowed_devices(user: dict) -> set[str] | None:
    """Device ids this user may see. None = all (admin). A customer without a tenant sees nothing."""
    if user["role"] == "admin":
        return None
    if user.get("tenant_id") is None:
        return set()
    with get_engine().connect() as conn:
        return {r[0] for r in conn.execute(
            select(tenant_devices.c.compactor_id).where(tenant_devices.c.tenant_id == user["tenant_id"]))}


def require_device(user: dict, compactor_id: str):
    """404, not 403: another customer must not learn that a device id exists."""
    allowed = allowed_devices(user)
    if allowed is not None and compactor_id not in allowed:
        raise HTTPException(404, f"Unknown compactor '{compactor_id}'")


def key_or_admin(request: Request, x_api_key: str | None = Header(default=None),
                 authorization: str | None = Header(default=None)):
    """Machine key, or a signed-in admin. Used by actions on the Europress analysis (all customers' data)."""
    expected = os.getenv("INGEST_API_KEY", "")
    if expected and x_api_key and hmac.compare_digest(x_api_key, expected):
        return
    if not enforced():
        if expected:
            raise HTTPException(401, "Missing or wrong X-API-Key")
        return
    require_admin(current_user(request, authorization))


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    company: str = Field(min_length=2, max_length=120)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


@router.post("/api/auth/register", status_code=202)
def register(body: RegisterIn):
    """Creates a PENDING account with no tenant and no devices. Same answer if the e-mail is already taken."""
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid e-mail address")
    digest = hash_password(body.password)
    with get_engine().begin() as conn:
        waiting = conn.execute(select(func.count()).select_from(users).where(users.c.status == "pending")).scalar()
        if waiting >= MAX_PENDING:
            raise HTTPException(503, "Registration is busy, try again later")
        if conn.execute(select(users.c.id).where(users.c.email == email)).first() is None:
            conn.execute(insert(users).values(email=email, password_hash=digest, role="customer", status="pending",
                                              company_requested=body.company.strip(), failed_logins=0, created_at=_now()))
    return {"status": "pending", "message": "Thanks. An administrator will check your request before you can sign in."}


def _bad_login():
    return HTTPException(401, "Wrong e-mail or password, or too many tries. Wait a few minutes.")


@router.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    from app import provision
    email = body.email.strip().lower()
    with get_engine().connect() as conn:
        u = conn.execute(select(users).where(users.c.email == email)).mappings().first()
    if u is None:
        verify_password(body.password, _DUMMY_HASH)
        raise _bad_login()
    if u["locked_until"] and _utc(u["locked_until"]) > _now():
        raise _bad_login()
    if not verify_password(body.password, u["password_hash"]):
        failed = (u["failed_logins"] or 0) + 1
        lock = _now() + timedelta(minutes=LOCK_MINUTES) if failed >= MAX_FAILED else None
        with get_engine().begin() as conn:
            conn.execute(update(users).where(users.c.id == u["id"]).values(
                failed_logins=0 if lock else failed, locked_until=lock))
        raise _bad_login()
    if u["status"] != "active":
        raise HTTPException(403, "Your account is waiting for approval" if u["status"] == "pending"
                            else "This account cannot sign in")

    if u["role"] != "admin":
        with get_engine().connect() as conn:
            t_status = conn.execute(select(tenants.c.status).where(tenants.c.id == u["tenant_id"])).scalar()
        if t_status != "active":
            raise HTTPException(403, "This customer account is suspended")

    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(hours=SESSION_HOURS)
    with get_engine().begin() as conn:
        conn.execute(delete(auth_sessions).where(auth_sessions.c.expires_at < _now()))
        conn.execute(insert(auth_sessions).values(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                                  user_id=u["id"], expires_at=expires))
        conn.execute(update(users).where(users.c.id == u["id"]).values(failed_logins=0, locked_until=None))
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True, samesite="strict",
                        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true")
    # Only here does the backend hold the plain password, so the Grafana account is made at first sign-in.
    grafana_ready = provision.ensure_grafana_user(dict(u), body.password) if u["role"] == "customer" else True
    return {"token": token, "expires_at": expires, "role": u["role"], "grafana_ready": grafana_ready}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response, authorization: str | None = Header(default=None)):
    token = _token_from(request, authorization)
    if token:
        with get_engine().begin() as conn:
            conn.execute(delete(auth_sessions).where(
                auth_sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    response.delete_cookie(COOKIE)
    return {"status": "signed out"}


@router.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    allowed = allowed_devices(user)
    name = None
    if user.get("tenant_id") is not None:
        with get_engine().connect() as conn:
            name = conn.execute(select(tenants.c.name).where(tenants.c.id == user["tenant_id"])).scalar()
    return {"email": user["email"], "role": user["role"], "tenant": name,
            "devices": None if allowed is None else sorted(allowed),
            "grafana_url": os.getenv("PUBLIC_GRAFANA_URL", "http://localhost:3000")}
