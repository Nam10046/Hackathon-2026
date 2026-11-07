"""Backend API. Owner: backend person. Endpoints must match CONTRACT.md."""
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app import analysis, auth, booking, cockpit, model_health, prices, rating, service, tenants
from app.auth import allowed_devices, current_user, require_device
from app.security import require_key
from app.ai import ml
from app.db import alerts, get_engine, init_db, materials, readings
from app.schemas import (
    Alert, BulkReadingsIn, HealthResponse, Material, ReadingIn, ReadingOut, ReadingResult, Status,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create tables + starter data; wait for the database if it is still starting
    for attempt in range(30):
        try:
            init_db()
            break
        except Exception as e:
            print(f"database not ready ({type(e).__name__}), retry {attempt + 1}/30…", flush=True)
            time.sleep(2)
    else:
        raise RuntimeError("could not connect to the database — is the postgres container running?")
    auth.ensure_admin()
    ml.load_all()  # plug-in models from models/
    yield


app = FastAPI(title="Smart Compactor API", version=os.getenv("APP_VERSION", "0.2.0"), lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(cockpit.router)
app.include_router(model_health.router)
app.include_router(booking.router)
app.include_router(prices.router)
app.include_router(rating.router)
app.include_router(analysis.router)
app.include_router(auth.router)
app.include_router(tenants.router)
STATIC = Path(__file__).parent / "static"
PORTAL = STATIC / "portal.html"
DEV_FILES = {"mock.js", "fixtures.json"}
app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")   # public design files, no data


def mock_enabled() -> bool:
    """Frontend mock mode: off unless asked for, and never on an HTTPS deployment."""
    return os.getenv("FRONTEND_MOCK", "false").lower() == "true" and os.getenv("COOKIE_SECURE", "false").lower() != "true"


@app.api_route("/dev/{name}", methods=["GET", "HEAD"], include_in_schema=False)
def dev_file(name: str):
    if not mock_enabled() or name not in DEV_FILES:
        raise HTTPException(404)
    return FileResponse(STATIC / "dev" / name)


@app.get("/portal", response_class=HTMLResponse, include_in_schema=False)
def portal():
    return PORTAL.read_text(encoding="utf-8")


@app.get("/api/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "version": app.version}


@app.post("/api/readings", response_model=ReadingResult, dependencies=[Depends(require_key)])
def post_reading(r: ReadingIn):
    try:
        return service.ingest(r.model_dump())
    except KeyError:
        raise HTTPException(404, f"Unknown compactor '{r.compactor_id}'")


@app.post("/api/readings/bulk", dependencies=[Depends(require_key)])
def post_bulk(body: BulkReadingsIn):
    total_alerts = 0
    for r in sorted(body.readings, key=lambda x: (x.ts is None, x.ts)):
        try:
            total_alerts += len(service.ingest(r.model_dump())["alerts"])
        except KeyError:
            raise HTTPException(404, f"Unknown compactor '{r.compactor_id}'")
    return {"stored": len(body.readings), "alerts": total_alerts}


@app.get("/api/compactors", response_model=list[Status])
def list_compactors(user: dict = Depends(current_user)):
    allowed = allowed_devices(user)
    return [s for s in service.get_status() if allowed is None or s["compactor_id"] in allowed]


@app.get("/api/compactors/{cid}", response_model=Status)
def get_compactor(cid: str, user: dict = Depends(current_user)):
    require_device(user, cid)
    rows = service.get_status(cid)
    if not rows:
        raise HTTPException(404, f"Unknown compactor '{cid}'")
    return rows[0]


@app.get("/api/compactors/{cid}/readings", response_model=list[ReadingOut])
def get_readings(cid: str, limit: int = 500, user: dict = Depends(current_user)):
    require_device(user, cid)
    q = (select(readings.c.ts, readings.c.weight_kg, readings.c.fill_pct)
         .where(readings.c.compactor_id == cid).order_by(readings.c.ts.desc()).limit(limit))
    with get_engine().connect() as conn:
        rows = [dict(r) for r in conn.execute(q).mappings()]
    return list(reversed(rows))


@app.get("/api/alerts", response_model=list[Alert])
def get_alerts(compactor_id: str | None = None, limit: int = 50, user: dict = Depends(current_user)):
    q = select(alerts).order_by(alerts.c.ts.desc(), alerts.c.id.desc()).limit(limit)
    if compactor_id:
        require_device(user, compactor_id)
        q = q.where(alerts.c.compactor_id == compactor_id)
    allowed = allowed_devices(user)
    if allowed is not None:
        q = q.where(alerts.c.compactor_id.in_(allowed))
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


@app.get("/api/pickups")
def list_pickups(limit: int = 100, user: dict = Depends(current_user)):
    """Every lift: booked / done, verdict, kg, money, CO2, invoice check (app/pickups.py)."""
    from sqlalchemy import select
    from app.db import get_engine, pickups
    q = select(pickups).order_by(pickups.c.id.desc()).limit(min(limit, 1000))
    allowed = allowed_devices(user)
    if allowed is not None:
        q = q.where(pickups.c.compactor_id.in_(allowed))
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


@app.get("/api/materials", response_model=list[Material])
def get_materials():
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(select(materials)).mappings()]


@app.get("/api/models")
def get_models():
    return ml.list_models()


@app.post("/api/models/reload", dependencies=[Depends(require_key)])
def reload_models():
    """Call after copying a new model folder into models/ — no restart needed."""
    return {"loaded": ml.load_all()}
