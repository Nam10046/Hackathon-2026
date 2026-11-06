"""Database tables and connection. Owner: backend person.

Uses PostgreSQL in Docker (DATABASE_URL) and SQLite for quick local runs/tests.
Table layout must match CONTRACT.md section 3.
"""
import os

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
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
)

readings = Table(
    "readings", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("compactor_id", String, ForeignKey("compactors.id"), nullable=False, index=True),
    Column("ts", DateTime(timezone=True), nullable=False, index=True),
    Column("weight_kg", Float, nullable=False),
    Column("fill_pct", Float),
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

# PLACEHOLDER numbers — replace with real prices/densities from Europress or recyclers
SEED_MATERIALS = [
    {"name": "cardboard", "price_eur_per_kg": 0.08, "density_min": 150, "density_max": 450, "co2_factor": 0.9},
    {"name": "plastic", "price_eur_per_kg": 0.05, "density_min": 100, "density_max": 350, "co2_factor": 1.5},
    {"name": "mixed", "price_eur_per_kg": -0.15, "density_min": 250, "density_max": 650, "co2_factor": 0.0},
]
SEED_COMPACTORS = [
    {"id": "C1", "name": "Warehouse cardboard", "material": "cardboard", "capacity_kg": 2000, "volume_m3": 8},
    {"id": "C2", "name": "Store plastic", "material": "plastic", "capacity_kg": 1500, "volume_m3": 8},
    {"id": "C3", "name": "Mixed waste", "material": "mixed", "capacity_kg": 4000, "volume_m3": 8},
]

_engine = None


def get_engine():
    """Create the engine once. Reads DATABASE_URL at first use (so tests can override it)."""
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", "sqlite:///./local.db")
        _engine = create_engine(url, future=True)
    return _engine


def reset_engine():
    """Used by tests to switch database."""
    global _engine
    _engine = None


def init_db():
    """Create tables and add starter data if empty."""
    engine = get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.execute(select(materials.c.name)).first() is None:
            conn.execute(insert(materials), SEED_MATERIALS)
        if conn.execute(select(compactors.c.id)).first() is None:
            conn.execute(insert(compactors), SEED_COMPACTORS)
