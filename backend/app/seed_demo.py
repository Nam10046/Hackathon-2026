"""Two demo customers with their own devices and made-up history. Opt-in, safe to run again, deletes nothing.
Everything it writes is marked as simulated, so dashboards can say so: readings have edge_quality='simulated', alerts
start with "Simulated demo:". No AI model or rule produced these alerts.
    docker compose exec backend python -m app.seed_demo
Uses separate devices (A-1xx, B-2xx), so the ESP32's C1-C3 data is never mixed with made-up numbers.
Passwords: DEMO_CUSTOMER1_PASSWORD / DEMO_CUSTOMER2_PASSWORD, otherwise random and printed once."""
import os
import random
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update

from app import auth, provision
from app.ai import value
from app.db import alerts, compactor_status, compactors, get_engine, init_db, materials, pickups, readings, tenants, users

CUSTOMERS = [
    {"name": "Demo Customer 1", "email": "customer1@demo.local", "pw_env": "DEMO_CUSTOMER1_PASSWORD", "devices": [
        {"id": "A-101", "name": "Demo 1 cardboard press", "material": "cardboard", "capacity_kg": 2000, "volume_m3": 8, "on_call_threshold_pct": 80},
        {"id": "A-102", "name": "Demo 1 plastic press", "material": "plastic", "capacity_kg": 1500, "volume_m3": 8, "on_call_threshold_pct": 80}]},
    {"name": "Demo Customer 2", "email": "customer2@demo.local", "pw_env": "DEMO_CUSTOMER2_PASSWORD", "devices": [
        {"id": "B-201", "name": "Demo 2 mixed waste press", "material": "mixed", "capacity_kg": 4000, "volume_m3": 8, "on_call_threshold_pct": 85},
        {"id": "B-202", "name": "Demo 2 cardboard press", "material": "cardboard", "capacity_kg": 2500, "volume_m3": 10, "on_call_threshold_pct": 80}]},
]
FEE = {"cardboard": 45.0, "plastic": 45.0, "mixed": 85.0}
DAYS = 14
SIM = "Simulated demo: "


def mark_simulated(conn):
    """Earlier seeds wrote no marker. Labels the rows of the demo devices; deletes and renames nothing else."""
    ids = [d["id"] for c in CUSTOMERS for d in c["devices"]]
    conn.execute(update(readings).where(readings.c.compactor_id.in_(ids), readings.c.seq.is_(None)).values(edge_quality="simulated"))
    old = select(alerts.c.id, alerts.c.message).where(alerts.c.compactor_id.in_(ids), alerts.c.message.not_like(SIM + "%"))
    for row in conn.execute(old).all():
        conn.execute(update(alerts).where(alerts.c.id == row.id).values(message=SIM + row.message))


def fill_history(conn, dev, mat):
    """Hourly readings: the press fills up, a truck empties it, each lift is judged. Same shape as the live tables."""
    rng = random.Random(dev["id"])
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    t, load, rate = now - timedelta(days=DAYS), rng.uniform(5, 25), rng.uniform(0.7, 1.3)
    rows, found, lifts = [], [], []
    limit = dev["on_call_threshold_pct"]
    while t <= now:
        load += rate * rng.uniform(0.6, 1.4)
        if load >= limit + rng.uniform(-30, 22):
            kg = load / 100 * dev["capacity_kg"]
            verdict = "TOO_EARLY" if load < limit - 20 else "TOO_LATE" if load > 98 else "ON_TIME"
            val, fee = kg * mat["price_eur_per_kg"], FEE[dev["material"]]
            bad_invoice = rng.random() < 0.2
            inv_kg = kg * (0.9 if bad_invoice else 1.0)
            lifts.append(dict(compactor_id=dev["id"], status="done", kind="booked", created_at=t - timedelta(hours=4),
                              booked_at=t - timedelta(hours=4), booked_load_pct=round(load - 3, 1), truck_due=t, truck_late=False,
                              done_at=t, load_before_pct=round(load, 1), kg_collected=round(kg, 1), full_hours=0.0, wait_hours=4.0,
                              verdict=verdict, verdict_reason=f"emptied at {load:.0f}%", value_eur=round(val, 2), fee_eur=fee,
                              net_eur=round(val - fee, 2), co2_kg=round(kg * mat["co2_factor"], 1), invoice_kg=round(inv_kg, 1),
                              invoice_fee_eur=fee, invoice_net_eur=round(inv_kg * mat["price_eur_per_kg"] - fee, 2),
                              invoice_check="WEIGHT_MISMATCH" if bad_invoice else "OK",
                              claim_eur=round(abs(kg - inv_kg) * abs(mat["price_eur_per_kg"]), 2) if bad_invoice else 0.0))
            found.append(dict(compactor_id=dev["id"], ts=t, type="emptied", severity="info", message=f"{SIM}Emptied at {load:.0f}%"))
            if verdict == "TOO_EARLY":
                found.append(dict(compactor_id=dev["id"], ts=t, type="ml_premature_unjustified", severity="warning",
                                  message=f"{SIM}example of an AI finding, lift too early ({load:.0f}% full)"))
            elif verdict == "TOO_LATE":
                found.append(dict(compactor_id=dev["id"], ts=t, type="ml_delayed_collection", severity="warning",
                                  message=f"{SIM}example of an AI finding, lift too late ({load:.0f}% full)"))
            load = rng.uniform(0, 3)
        if rng.random() < 0.012:
            found.append(dict(compactor_id=dev["id"], ts=t, type="contamination", severity="warning",
                              message=f"{SIM}example of a rule finding, density above normal for {dev['material']}"))
        kg = load / 100 * dev["capacity_kg"]
        rows.append(dict(compactor_id=dev["id"], ts=t, weight_kg=round(kg, 1), fill_pct=round(min(load, 100), 1),
                         edge_quality="simulated"))
        t += timedelta(hours=1)
    conn.execute(insert(readings), rows)
    conn.execute(insert(alerts), found)
    conn.execute(insert(pickups), lifts)
    conn.execute(insert(pickups).values(compactor_id=dev["id"], status="scheduled", kind="fixed_route", created_at=now,
                                        trigger_load_pct=limit, truck_due=now + timedelta(hours=max(1, (limit - load) / rate))))
    conn.execute(compactor_status.delete().where(compactor_status.c.compactor_id == dev["id"]))
    conn.execute(insert(compactor_status).values(
        compactor_id=dev["id"], weight_kg=round(kg, 1), fill_pct=round(min(load, 100), 1), load_pct=round(load, 1),
        density_kg_m3=round(kg / (dev["volume_m3"] * max(load, 1) / 100), 1), **value.material_value(kg, mat),
        hours_to_full=round(max(0.0, (100 - load) / rate), 1), last_ts=now))
    return len(rows)


def main():
    init_db()
    engine = get_engine()
    with engine.begin() as conn:
        mark_simulated(conn)
    for c in CUSTOMERS:
        with engine.begin() as conn:
            for dev in c["devices"]:
                if conn.execute(select(compactors.c.id).where(compactors.c.id == dev["id"])).first() is None:
                    conn.execute(insert(compactors).values(**dev))
                if conn.execute(select(readings.c.id).where(readings.c.compactor_id == dev["id"]).limit(1)).first() is None:
                    mat = dict(conn.execute(select(materials).where(materials.c.name == dev["material"])).mappings().first())
                    print(f"{dev['id']}: {fill_history(conn, dev, mat)} readings")
            tid = conn.execute(select(tenants.c.id).where(tenants.c.name == c["name"])).scalar()
        if tid is None:
            tid = provision.provision_tenant(c["name"])["id"]
            print(f"customer '{c['name']}' created")
        for dev in c["devices"]:
            provision.assign_device(tid, dev["id"], "seed_demo")
        with engine.connect() as conn:
            provision.push_dashboards(conn.execute(select(tenants.c.grafana_org_id).where(tenants.c.id == tid)).scalar())
        with engine.connect() as conn:
            known = conn.execute(select(users.c.id).where(users.c.email == c["email"])).first()
        if known is None:
            password = os.getenv(c["pw_env"]) or secrets.token_urlsafe(14)
            with engine.begin() as conn:
                uid = conn.execute(insert(users).values(
                    email=c["email"], password_hash=auth.hash_password(password), role="customer", status="active",
                    tenant_id=tid, failed_logins=0, created_at=datetime.now(timezone.utc), decided_by="seed_demo",
                    decided_at=datetime.now(timezone.utc))).inserted_primary_key[0]
                u = dict(conn.execute(select(users).where(users.c.id == uid)).mappings().first())
            ok = provision.ensure_grafana_user(u, password)
            print(f"login {c['email']}" + ("" if os.getenv(c["pw_env"]) else f" / {password}") + ("" if ok else "  (GRAFANA NOT READY)"))
        else:
            print(f"login {c['email']} already exists, password unchanged")


if __name__ == "__main__":
    main()
