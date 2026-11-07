"""Database tables and connection. Owner: backend person.

Uses PostgreSQL in Docker (DATABASE_URL) and SQLite for quick local runs/tests.
Table layout must match CONTRACT.md section 3.
"""
import os

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
    create_engine, insert, select,
)

metadata = MetaData()

materials = Table(
    "materials", metadata,
    Column("name", String, primary_key=True),
    Column("price_eur_per_kg", Float, nullable=False),  # + earn, - pay (customer types it in as € per tonne)
    Column("density_min", Float, nullable=False),        # kg/m3, normal compacted range
    Column("density_max", Float, nullable=False),
    Column("co2_factor", Float, nullable=False),         # kg CO2 saved per kg recycled
    Column("lift_fee_eur", Float),                       # cost per lift (lift fee + transport), customer types it in
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
    Column("customer_name", String),       # who owns it (the customer sees only their own compactors on the user platform)
    Column("operator_name", String),       # the waste company that empties it
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

# An invoice from a waste company, typed in by the customer (Analysis -> Invoices) and checked against what the board measured
invoices = Table(
    "invoices", metadata,
    Column("invoice_id", String, primary_key=True),       # the waste company's invoice number
    Column("customer_name", String, nullable=False, index=True),
    Column("operator_name", String, nullable=False),
    Column("period_from", Date, nullable=False),
    Column("period_to", Date, nullable=False),
    Column("total_eur", Float, nullable=False),            # the total printed on the invoice
    Column("entered_by", String),
    Column("entered_at", DateTime(timezone=True)),
    # filled by app/invoice_check.py
    Column("checked_at", DateTime(timezone=True)),
    Column("suggestion", String),                          # APPROVE | CHECK  (a person decides)
    Column("overcharged_eur", Float),                      # proven by our measurement: billed more than measured / contract
    Column("unverified_eur", Float),                       # surcharges / penalties the sensor cannot prove: ask for evidence
    Column("lines_ok", Integer),
    Column("lines_total", Integer),
    Column("summary", String),                             # plain-language result
)
invoice_lines = Table(
    "invoice_lines", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("invoice_id", String, ForeignKey("invoices.invoice_id"), nullable=False, index=True),
    Column("line_no", Integer, nullable=False),
    Column("line_type", String, nullable=False),           # LIFT_FEE | PROCESSING | MATERIAL_CREDIT | HAULAGE | SURCHARGE | PENALTY | OTHER
    Column("compactor_id", String),
    Column("service_date", Date),
    Column("quantity", Float),
    Column("unit", String),                                # lift | t | kg | pcs
    Column("unit_price_eur", Float),
    Column("amount_eur", Float, nullable=False),           # + charge, - credit
    # filled by app/invoice_check.py
    Column("check_status", String),                        # OK | WRONG_PRICE | NO_LIFT | DUPLICATE | WEIGHT_MISMATCH | NO_EVIDENCE | UNKNOWN_COMPACTOR
    Column("expected_eur", Float),                         # what it should be from our measurement + the contract
    Column("difference_eur", Float),                       # amount - expected: + = charged too much
    Column("check_reason", String),
)

# A person's decision on a whole invoice (Analysis page). Never updated: the newest row counts, the rest is the history.
invoice_decisions = Table(
    "invoice_decisions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("invoice_id", String, nullable=False, index=True),
    Column("decision", String, nullable=False),        # APPROVE | REJECT | HOLD
    Column("decided_by", String, nullable=False),
    Column("role", String, nullable=False),            # admin | customer
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
    {"name": "cardboard", "price_eur_per_kg": 0.08, "density_min": 150, "density_max": 450, "co2_factor": 0.9, "lift_fee_eur": 45},
    {"name": "biowaste", "price_eur_per_kg": -0.06, "density_min": 250, "density_max": 700, "co2_factor": 0.3, "lift_fee_eur": 60},
    {"name": "mixed", "price_eur_per_kg": -0.15, "density_min": 250, "density_max": 650, "co2_factor": 0.0, "lift_fee_eur": 85},
]
DEMO_CUSTOMER = os.getenv("DEMO_CUSTOMER", "Demo Customer (site S1)")
SEED_COMPACTORS = [
    # the ESP32 edge node (site S1) is our demo CUSTOMER: its 3 compactors, emptied by 2 waste companies
    {"id": "C1", "name": "Warehouse cardboard", "material": "cardboard", "capacity_kg": 2000, "volume_m3": 8, "on_call_threshold_pct": 80,
     "customer_name": DEMO_CUSTOMER, "operator_name": "Hauler Alpha"},
    {"id": "C2", "name": "Bio waste", "material": "biowaste", "capacity_kg": 3000, "volume_m3": 8, "on_call_threshold_pct": 80,
     "customer_name": DEMO_CUSTOMER, "operator_name": "Hauler Beta"},
    {"id": "C3", "name": "Mixed waste", "material": "mixed", "capacity_kg": 4000, "volume_m3": 8, "on_call_threshold_pct": 85,
     "customer_name": DEMO_CUSTOMER, "operator_name": "Hauler Alpha"},
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
    have_c = {c["name"] for c in inspect(engine).get_columns("compactors")}
    for col in [c for c in ("customer_name", "operator_name") if c not in have_c]:
        with engine.begin() as conn:   # older databases: who owns / empties each compactor
            conn.execute(text(f"ALTER TABLE compactors ADD COLUMN {col} VARCHAR"))
            for c in SEED_COMPACTORS:
                conn.execute(compactors.update().where(compactors.c.id == c["id"]).values(**{col: c[col]}))
    if "lift_fee_eur" not in {c["name"] for c in inspect(engine).get_columns("materials")}:
        with engine.begin() as conn:   # older databases: add the column, start from the placeholder fees
            conn.execute(text("ALTER TABLE materials ADD COLUMN lift_fee_eur FLOAT"))
            for m in SEED_MATERIALS:
                conn.execute(materials.update().where(materials.c.name == m["name"]).values(lift_fee_eur=m["lift_fee_eur"]))
    have = {c["name"] for c in inspect(engine).get_columns("readings")}
    for col, typ in [("verified", "BOOLEAN"), ("seq", "INTEGER"), ("edge_quality", "VARCHAR"),
                     ("spikes_filtered", "INTEGER"), ("from_buffer", "BOOLEAN")]:
        if col not in have:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE readings ADD COLUMN {col} {typ}"))
    with engine.begin() as conn:
        if conn.execute(select(materials.c.name)).first() is None:
            conn.execute(insert(materials), SEED_MATERIALS)
        # the site has cardboard, mixed waste and BIO waste (no plastic): move older databases over once
        if conn.execute(select(materials.c.name).where(materials.c.name == "plastic")).first() is not None:
            bio = next(m for m in SEED_MATERIALS if m["name"] == "biowaste")
            if conn.execute(select(materials.c.name).where(materials.c.name == "biowaste")).first() is None:
                conn.execute(insert(materials), [bio])
            c2 = next(c for c in SEED_COMPACTORS if c["id"] == "C2")
            conn.execute(compactors.update().where(compactors.c.material == "plastic")
                         .values(material="biowaste", name=c2["name"], capacity_kg=c2["capacity_kg"]))
            conn.execute(materials.delete().where(materials.c.name == "plastic"))
        have_ids = {r[0] for r in conn.execute(select(compactors.c.id))}
        missing = [c for c in SEED_COMPACTORS if c["id"] not in have_ids]
        if missing:   # also adds compactors that were added to the seed later
            conn.execute(insert(compactors), missing)
