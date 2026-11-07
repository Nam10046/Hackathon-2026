"""Database tables and connection. Owner: backend person.

Uses PostgreSQL in Docker (DATABASE_URL) and SQLite for quick local runs/tests.
Table layout must match CONTRACT.md section 3.
"""
import os

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
    create_engine, insert, select,
)

metadata = MetaData()

materials = Table(
    "materials", metadata,
    Column("name", String, primary_key=True),
    Column("price_eur_per_kg", Float, nullable=False),  # + earn, - pay
    Column("density_min", Float, nullable=False),        # kg/m3, normal compacted range
    Column("density_max", Float, nullable=False),
    Column("co2_factor", Float, nullable=False),         # kg CO2 saved per kg recycled
)

compactors = Table(
    "compactors", metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("material", String, ForeignKey("materials.name"), nullable=False),
    Column("capacity_kg", Float, nullable=False),
    Column("volume_m3", Float, nullable=False),
    # SETTING from SMART: fill % at which a truck is ordered (on-call). Used by the live lift model. NULL = unknown
    Column("on_call_threshold_pct", Float),
)

readings = Table(
    "readings", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("compactor_id", String, ForeignKey("compactors.id"), nullable=False, index=True),
    Column("ts", DateTime(timezone=True), nullable=False, index=True),
    Column("weight_kg", Float, nullable=False),
    Column("fill_pct", Float),
    # signed by the device and checked: True = verified, False = signature wrong, NULL = not signed / no key set
    Column("verified", Boolean),
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("compactor_id", String, ForeignKey("compactors.id"), nullable=False, index=True),
    Column("ts", DateTime(timezone=True), nullable=False, index=True),
    Column("type", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("message", String, nullable=False),
)

compactor_status = Table(
    "compactor_status", metadata,
    Column("compactor_id", String, ForeignKey("compactors.id"), primary_key=True),
    Column("weight_kg", Float),
    Column("fill_pct", Float),
    Column("load_pct", Float),
    Column("density_kg_m3", Float),
    Column("value_eur", Float),
    Column("co2_saved_kg", Float),
    Column("hours_to_full", Float),
    Column("last_ts", DateTime(timezone=True)),
)

# Human decisions on recommended actions (Customer Value Cockpit). Never deleted = audit trail.
action_decisions = Table(
    "action_decisions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("action_id", String, nullable=False, index=True),
    Column("decision", String, nullable=False),        # APPROVE | REJECT | REVERT
    Column("decided_by", String, nullable=False),
    Column("note", String),
    Column("decided_at", DateTime(timezone=True), nullable=False),
)

# Was a live alert right? Filled in by the person who checked it on site. Gives the model's LIVE precision.
alert_feedback = Table(
    "alert_feedback", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("alert_id", Integer, ForeignKey("alerts.id"), nullable=False, index=True),
    Column("verdict", String, nullable=False),         # CORRECT | FALSE_ALARM
    Column("decided_by", String, nullable=False),
    Column("note", String),
    Column("decided_at", DateTime(timezone=True), nullable=False),
)

# PLACEHOLDER numbers — replace with real prices/densities from Europress or recyclers
SEED_MATERIALS = [
    {"name": "cardboard", "price_eur_per_kg": 0.08, "density_min": 150, "density_max": 450, "co2_factor": 0.9},
    {"name": "plastic", "price_eur_per_kg": 0.05, "density_min": 100, "density_max": 350, "co2_factor": 1.5},
    {"name": "mixed", "price_eur_per_kg": -0.15, "density_min": 250, "density_max": 650, "co2_factor": 0.0},
]
SEED_COMPACTORS = [
    {"id": "C1", "name": "Warehouse cardboard", "material": "cardboard", "capacity_kg": 2000, "volume_m3": 8, "on_call_threshold_pct": 80},
    {"id": "C2", "name": "Store plastic", "material": "plastic", "capacity_kg": 1500, "volume_m3": 8, "on_call_threshold_pct": 80},
    {"id": "C3", "name": "Mixed waste", "material": "mixed", "capacity_kg": 4000, "volume_m3": 8, "on_call_threshold_pct": 85},
]

_engine = None


def normalize_url(url: str) -> str:
    """Accept the URL exactly as TigerData/Rahti give it ("postgres://..." or "postgresql://...")."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def get_engine():
    """Create the engine once. Reads DATABASE_URL at first use (so tests can override it)."""
    global _engine
    if _engine is None:
        url = normalize_url(os.getenv("DATABASE_URL", "sqlite:///./local.db"))
        _engine = create_engine(url, future=True, pool_pre_ping=True)  # pre_ping: survive cloud DB idle disconnects
    return _engine


def reset_engine():
    """Used by tests to switch database."""
    global _engine
    _engine = None


def init_db():
    """Create tables and add starter data if empty."""
    engine = get_engine()
    metadata.create_all(engine)
    # small migration for databases created before the column existed (create_all never alters a table)
    from sqlalchemy import inspect, text
    if "on_call_threshold_pct" not in {c["name"] for c in inspect(engine).get_columns("compactors")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE compactors ADD COLUMN on_call_threshold_pct FLOAT"))
    if "verified" not in {c["name"] for c in inspect(engine).get_columns("readings")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE readings ADD COLUMN verified BOOLEAN"))
    with engine.begin() as conn:
        if conn.execute(select(materials.c.name)).first() is None:
            conn.execute(insert(materials), SEED_MATERIALS)
        if conn.execute(select(compactors.c.id)).first() is None:
            conn.execute(insert(compactors), SEED_COMPACTORS)
