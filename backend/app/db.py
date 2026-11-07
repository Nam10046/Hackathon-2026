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
    # what the edge node itself decided (firmware/edge_node); NULL for plain sensors
    Column("seq", Integer),
    Column("edge_quality", String),          # stable | settling | stuck ...
    Column("spikes_filtered", Integer),      # spikes the board removed before sending
    Column("from_buffer", Boolean),          # sent later from the board's offline buffer
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

# one row per lift: booked -> (truck arrives) -> done, judged, priced, invoice checked (app/pickups.py)
pickups = Table(
    "pickups", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("compactor_id", String, ForeignKey("compactors.id"), nullable=False, index=True),
    Column("status", String, nullable=False),            # scheduled | booked | done | cancelled
    Column("kind", String, nullable=False),              # booked (by us) | fixed_route (old schedule) | manual
    Column("created_at", DateTime(timezone=True)),
    Column("trigger_load_pct", Float),                   # fixed_route: comes at this load
    Column("booked_at", DateTime(timezone=True)),
    Column("booked_load_pct", Float),
    Column("truck_due", DateTime(timezone=True)),
    Column("truck_late", Boolean),
    Column("cmd_sent_at", DateTime(timezone=True)),
    Column("done_at", DateTime(timezone=True), index=True),
    Column("load_before_pct", Float),
    Column("kg_collected", Float),
    Column("full_hours", Float),                         # site hours it was full before the lift
    Column("wait_hours", Float),                         # site hours from booking to lift
    Column("verdict", String),                           # ON_TIME | TOO_EARLY | TOO_LATE
    Column("verdict_reason", String),
    Column("value_eur", Float),                          # material value: + earned, - paid
    Column("fee_eur", Float),                            # contract lift fee
    Column("net_eur", Float),
    Column("co2_kg", Float),
    Column("invoice_kg", Float),
    Column("invoice_fee_eur", Float),
    Column("invoice_net_eur", Float),
    Column("invoice_check", String),                     # OK | WEIGHT_MISMATCH | WRONG_FEE | both
    Column("claim_eur", Float),
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
    have = {c["name"] for c in inspect(engine).get_columns("readings")}
    for col, typ in [("verified", "BOOLEAN"), ("seq", "INTEGER"), ("edge_quality", "VARCHAR"),
                     ("spikes_filtered", "INTEGER"), ("from_buffer", "BOOLEAN")]:
        if col not in have:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE readings ADD COLUMN {col} {typ}"))
    with engine.begin() as conn:
        if conn.execute(select(materials.c.name)).first() is None:
            conn.execute(insert(materials), SEED_MATERIALS)
        have_ids = {r[0] for r in conn.execute(select(compactors.c.id))}
        missing = [c for c in SEED_COMPACTORS if c["id"] not in have_ids]
        if missing:   # also adds compactors that were added to the seed later
            conn.execute(insert(compactors), missing)
