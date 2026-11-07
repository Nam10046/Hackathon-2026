"""Pickups: the part of the product that turns ESP32 weights into decisions and money.

Loop (all automatic, driven by the readings of the edge node):
  1. load reaches the compactor's on-call threshold  -> a truck is BOOKED (alert pickup_booked)
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

from app.db import pickups, readings

SCALE = float(os.getenv("DEMO_TIME_SCALE", "1"))   # site hours per real hour
SITE_ID = os.getenv("SITE_ID", "S1")
FEE_EUR = {"cardboard": 45.0, "plastic": 45.0, "mixed": 85.0}   # PLACEHOLDER lift fee per material
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

    if p is None and load >= thr:                                    # 1. book a truck
        late = rng.random() < P_TRUCK_LATE
        lead = rng.uniform(9, 13) if late else rng.uniform(1.5, 3.5)    # site hours
        due = ts + real(lead)
        pid = conn.execute(insert(pickups).values(
            compactor_id=cid, status="booked", kind="booked", booked_at=ts, booked_load_pct=round(load, 1),
            truck_due=due, truck_late=late, created_at=ts)).inserted_primary_key[0]
        out_alerts.append({"type": "pickup_booked", "severity": "info",
                           "message": f"Truck booked automatically at {load:.0f}% (on-call {thr:.0f}%) — arrives in ~{lead:.0f} h "
                                      f"(pickup #{pid})"})
    elif p is not None and p["status"] == "scheduled" and load >= (p["trigger_load_pct"] or 0):
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

    price, fee = mat["price_eur_per_kg"], FEE_EUR.get(comp["material"], 50.0)
    value = kg * price                       # + we earn (cardboard), - we pay to get rid of it (mixed)
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
