"""Pickups: the part of the product that turns ESP32 weights into decisions and money.

Loop (driven by the readings of the edge node; only a PERSON books a truck):
  1. load reaches the compactor's on-call threshold  -> NOTICE only (alert pickup_needed, once per fill cycle)
     a person presses "Book truck" (Grafana booking panel -> POST /api/pickups/book) -> BOOKED, truck goes now
  2. the booked time arrives                         -> a command goes to the board: "empty C2"  (Node-RED -> MQTT)
  3. the board itself detects the emptying           -> the pickup is CLOSED and JUDGED:
        ON_TIME    emptied near full, not overflowing
        TOO_EARLY  emptied well below the threshold   -> a truck trip paid for half a container
        TOO_LATE   it was full for >= 2 site hours    -> overflow / side waste
     + kg collected, money (material value - lift fee), CO2 saved
  4. the operator's INVOICE arrives (simulated)      -> checked against the kg WE measured -> claim if wrong

Demo realism (so all verdicts appear by themselves): some trucks are late, the old "fixed route" sometimes still
comes early, and some invoices are wrong. Times are in SITE hours: DEMO_TIME_SCALE=60 means 1 real minute = 1 site hour.
"""
import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update

from app.db import alerts, compactor_status, pickups, readings

SCALE = float(os.getenv("DEMO_TIME_SCALE", "1"))   # site hours per real hour
SITE_ID = os.getenv("SITE_ID", "S1")
FEE_EUR = {"cardboard": 45.0, "biowaste": 60.0, "mixed": 85.0}   # fallback only: the customer types the fee in (materials.lift_fee_eur)
FULL_PCT = 98            # counts as full
LATE_FULL_H = 2.0        # full this long before the lift -> TOO_LATE
EARLY_MARGIN = 20        # emptied more than this below the on-call threshold -> TOO_EARLY
P_TRUCK_LATE = float(os.getenv("DEMO_P_TRUCK_LATE", "0.12"))
P_FIXED_ROUTE = float(os.getenv("DEMO_P_FIXED_ROUTE", "0.15"))
P_INVOICE_KG = float(os.getenv("DEMO_P_INVOICE_KG", "0.15"))
P_INVOICE_FEE = float(os.getenv("DEMO_P_INVOICE_FEE", "0.10"))
RESEND_S = 90            # board did not empty after a command -> send it again


def site_h(td: timedelta) -> float:
    return td.total_seconds() / 3600 * SCALE


def real(site_hours: float) -> timedelta:
    return timedelta(hours=site_hours / SCALE)


def load_pct(weight_kg, fill_pct, cap):
    return max(max(weight_kg, 0) / cap * 100, fill_pct or 0)


def _open(conn, cid):
    return conn.execute(select(pickups).where(pickups.c.compactor_id == cid, pickups.c.status.in_(["booked", "scheduled"]))
                        .order_by(pickups.c.id.desc()).limit(1)).mappings().first()


def _cmd(p):
    return {"topic": f"site/{SITE_ID}/cmd", "compactor_id": p["compactor_id"], "action": "empty", "pickup_id": p["id"]}


def tick(conn, comp, mat, ts, load, emptied, before, rng=random):
    """Called for every stored reading. Returns (alerts, commands)."""
    out_alerts, cmds = [], []
    cid, thr = comp["id"], comp.get("on_call_threshold_pct") or 80
    now = datetime.now(timezone.utc)
    p = _open(conn, cid)

    if emptied and before is not None:
        out_alerts += close(conn, comp, mat, p, ts, before, rng)
        # next cycle: will the old fixed route still come by? (shows why booking on demand matters)
        if rng.random() < P_FIXED_ROUTE:
            trig = rng.uniform(30, max(31, thr - EARLY_MARGIN - 5))
            conn.execute(insert(pickups).values(compactor_id=cid, status="scheduled", kind="fixed_route",
                                                trigger_load_pct=round(trig, 1), created_at=ts))
        return out_alerts, cmds

    # 1. on-call level reached and no truck booked yet -> tell a person (once per fill cycle); we do NOT book
    if load >= thr and (p is None or p["status"] == "scheduled") and not _noticed(conn, cid):
        out_alerts.append({"type": "pickup_needed", "severity": "warning",
                           "message": f"{load:.0f}% full (on-call {thr:.0f}%) — book a truck on the Site now page"})

    if p is not None and p["status"] == "scheduled" and load >= (p["trigger_load_pct"] or 0):
        conn.execute(update(pickups).where(pickups.c.id == p["id"]).values(status="booked", truck_due=ts, cmd_sent_at=now))
        out_alerts.append({"type": "truck_arrived", "severity": "info",
                           "message": f"Old fixed-route truck arrived at only {load:.0f}% — not booked by us (pickup #{p['id']})"})
        cmds.append(_cmd(p))
    elif p is not None and p["status"] == "booked" and p["truck_due"] is not None and ts >= _utc(p["truck_due"]):
        sent = p["cmd_sent_at"]
        if sent is None or (now - _utc(sent)).total_seconds() > RESEND_S:  # 2. the truck is here
            conn.execute(update(pickups).where(pickups.c.id == p["id"]).values(cmd_sent_at=now))
            if sent is None:
                out_alerts.append({"type": "truck_arrived", "severity": "info",
                                   "message": f"Booked truck arrived at {load:.0f}%" + (" — it was late" if p["truck_late"] else "")
                                              + f" (pickup #{p['id']})"})
            cmds.append(_cmd(p))
    return out_alerts, cmds


def _utc(t):
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _noticed(conn, cid):
    """Was a pickup_needed notice already sent since the last emptying?"""
    last = conn.execute(select(pickups.c.done_at).where(pickups.c.compactor_id == cid, pickups.c.status == "done")
                        .order_by(pickups.c.done_at.desc()).limit(1)).first()
    q = select(alerts.c.id).where(alerts.c.compactor_id == cid, alerts.c.type == "pickup_needed")
    if last and last[0]:
        q = q.where(alerts.c.ts > last[0])
    return conn.execute(q.limit(1)).first() is not None


def book(conn, comp, ts, by="operator"):
    """A person pressed "Book truck": the truck goes NOW. The empty command for THIS compactor only goes to the board
    with the answer to its next reading (Node-RED -> MQTT site/<id>/cmd, same as the board's own "e" key).
    Returns (pickup_id, new). Pressing again while a truck is on its way re-sends the command (new = False).
    An open old fixed-route visit is replaced by this booking."""
    cid = comp["id"]
    p = _open(conn, cid)
    if p is not None and p["status"] == "booked":
        conn.execute(update(pickups).where(pickups.c.id == p["id"]).values(truck_due=ts, cmd_sent_at=None))
        return p["id"], False
    if p is not None:   # scheduled fixed-route visit -> the person's booking replaces it
        conn.execute(update(pickups).where(pickups.c.id == p["id"]).values(status="cancelled"))
    st = conn.execute(select(compactor_status.c.load_pct).where(compactor_status.c.compactor_id == cid)).first()
    load = st[0] if st and st[0] is not None else None
    pid = conn.execute(insert(pickups).values(
        compactor_id=cid, status="booked", kind="booked", booked_at=ts, booked_load_pct=round(load, 1) if load is not None else None,
        truck_due=ts, truck_late=False, created_at=ts)).inserted_primary_key[0]
    at = f" at {load:.0f}%" if load is not None else ""
    conn.execute(insert(alerts).values(compactor_id=cid, ts=ts, type="pickup_booked", severity="info",
                                       message=f"Truck booked by {by}{at} — emptying {cid} now (pickup #{pid})"))
    return pid, True


def costs(kg, mat, material=None):
    """LIVE estimate, kept simple on purpose: the customer types in 2 numbers per material.
      collection_cost = cost per lift (lift fee + transport)
      material_value  = kg x price (+ the waste company pays you, - you pay them)
      total cost      = collection_cost - material_value          · € per t = total cost / (kg / 1000)
    The full Europress formula (haulage, processing, surcharges, penalties, credits) needs the real invoice lines,
    so it is on the Analysis pages (cp_collections), not here."""
    t = max(kg, 0) / 1000
    lift = mat.get("lift_fee_eur") if mat.get("lift_fee_eur") is not None else FEE_EUR.get(material, 50.0)
    value = max(kg, 0) * (mat.get("price_eur_per_kg") or 0)
    total = lift - value
    return {"collection_cost": lift, "material_value": value, "total_customer_cost": total,
            "total_cost_eur_per_t": total / t if t else None}


def close(conn, comp, mat, p, ts, before, rng=random):
    """3 + 4: the board saw the container emptied -> pickup record, verdict, money, invoice check."""
    cid, cap, thr = comp["id"], comp["capacity_kg"], comp.get("on_call_threshold_pct") or 80
    lb = load_pct(before["weight_kg"], before.get("fill_pct"), cap)
    kg = max(0.0, before["weight_kg"] - (before.get("after_kg") or 0))

    # how long was it full before this lift? (readings since the previous closed pickup)
    prev = conn.execute(select(pickups.c.done_at).where(pickups.c.compactor_id == cid, pickups.c.status == "done")
                        .order_by(pickups.c.done_at.desc()).limit(1)).first()
    since = _utc(prev[0]) if prev and prev[0] else ts - real(72)
    first_full = conn.execute(select(readings.c.ts).where(
        readings.c.compactor_id == cid, readings.c.ts > since, readings.c.ts < ts,
        (readings.c.weight_kg >= cap * FULL_PCT / 100) | (readings.c.fill_pct >= FULL_PCT))
        .order_by(readings.c.ts).limit(1)).first()
    full_h = site_h(ts - _utc(first_full[0])) if first_full else 0.0

    if full_h >= LATE_FULL_H:
        verdict, why = "TOO_LATE", f"was full for {full_h:.1f} h before the truck came — overflow / side-waste risk"
    elif lb < thr - EARLY_MARGIN:
        verdict, why = "TOO_EARLY", f"emptied at only {lb:.0f}% — paid a full lift for {lb:.0f}% of a container"
    else:
        verdict, why = "ON_TIME", f"emptied at {lb:.0f}%, not overflowing"

    price = mat["price_eur_per_kg"]
    c = costs(kg, mat, comp["material"])
    fee = c["collection_cost"]               # what the truck visit costs
    value = c["material_value"]              # + we earn (cardboard), - we pay to get rid of it (mixed)
    co2 = kg * mat["co2_factor"]

    # the operator's invoice (simulated): usually right; sometimes the kg are "wrong in their favour"
    # (more kg when we pay per kg, fewer kg when they pay us), sometimes an old (higher) lift fee
    inv_kg, inv_fee = kg * (1 + rng.gauss(0, 0.01)), fee
    if rng.random() < P_INVOICE_KG:
        d = rng.uniform(0.06, 0.14)
        inv_kg = kg * (1 + d) if price < 0 else kg * (1 - d)
    if rng.random() < P_INVOICE_FEE:
        inv_fee = fee * 1.25
    problems, claim = [], 0.0
    if kg > 0 and abs(inv_kg - kg) / kg > 0.04:
        problems.append("WEIGHT_MISMATCH")
        claim += abs(inv_kg - kg) * abs(price)
    if inv_fee > fee + 0.01:
        problems.append("WRONG_FEE")
        claim += inv_fee - fee
    check = "+".join(problems) or "OK"
    inv_total = inv_kg * price - inv_fee

    vals = dict(status="done", done_at=ts, load_before_pct=round(lb, 1), kg_collected=round(kg, 1), full_hours=round(full_h, 1),
                verdict=verdict, verdict_reason=why, value_eur=round(value, 2), fee_eur=round(fee, 2),
                net_eur=round(value - fee, 2), co2_kg=round(co2, 1), invoice_kg=round(inv_kg, 1), invoice_fee_eur=round(inv_fee, 2),
                invoice_net_eur=round(inv_total, 2), invoice_check=check, claim_eur=round(claim, 2),
                wait_hours=round(site_h(ts - _utc(p["booked_at"])), 1) if p is not None and p["booked_at"] else None)
    if p is not None and p["status"] == "booked" and p["cmd_sent_at"] is not None:
        pid = p["id"]
        conn.execute(update(pickups).where(pickups.c.id == pid).values(**vals))
        kind = p["kind"]
    else:
        if p is not None:   # a booking/schedule was open but the container was emptied anyway (by hand) -> cancel it
            conn.execute(update(pickups).where(pickups.c.id == p["id"]).values(status="cancelled", done_at=ts))
        kind = "manual"
        pid = conn.execute(insert(pickups).values(compactor_id=cid, kind=kind, created_at=ts, **vals)).inserted_primary_key[0]

    sev = {"ON_TIME": "info", "TOO_EARLY": "warning", "TOO_LATE": "warning"}[verdict]
    out = [{"type": f"pickup_{verdict.lower()}", "severity": sev,
            "message": f"Pickup #{pid} ({kind.replace('_', ' ')}): {kg:.0f} kg {comp['material']}, {why}. "
                       f"Net {value - fee:+.0f} €, CO2 saved {co2:.0f} kg"}]
    if check != "OK":
        out.append({"type": "invoice_mismatch", "severity": "warning",
                    "message": f"Invoice for pickup #{pid}: {check.replace('+', ' and ').replace('_', ' ').lower()} — "
                               f"billed {inv_kg:.0f} kg / fee {inv_fee:.0f} €, we measured {kg:.0f} kg / contract fee {fee:.0f} €. "
                               f"Claim {claim:.0f} €"})
    return out
