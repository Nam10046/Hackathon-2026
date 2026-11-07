"""Business logic: store a reading, run the AI parts, update status. Owner: backend person."""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select

from app import pickups
from app.ai import anomaly, features, forecast, live_lift, ml, value
from app.db import alerts, compactor_status, compactors, get_engine, materials, readings

HISTORY_SIZE = 50  # how many previous readings the AI looks at


def _stretch(t, anchor):
    """Fast demo mode: turn real time into SITE time (DEMO_TIME_SCALE=60: 1 real minute = 1 site hour), so models
    trained on real hours (lift model, fill forecast) see the durations they expect."""
    return t if pickups.SCALE == 1 else anchor - (anchor - t) * pickups.SCALE


def _utc(ts):
    """Make every timestamp timezone-aware UTC (SQLite returns naive ones)."""
    if ts is None:
        return datetime.now(timezone.utc)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _load_pct(weight_kg, fill_pct, capacity_kg):
    by_weight = max(weight_kg, 0) / capacity_kg * 100
    return round(max(by_weight, fill_pct or 0), 1)


def _device_key(compactor_id: str):
    """DEVICE_KEYS="C1:secret1,C2:secret2" (backend .env). None = this device does not sign."""
    for part in os.getenv("DEVICE_KEYS", "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip() == compactor_id:
                return v.strip()
    return None


def verify_signature(reading: dict, ts_given: bool, ts) -> bool | None:
    """Edge node signs "id|seq|epoch|weight|fill" with HMAC-SHA256 (firmware/edge_node). None = cannot check."""
    sig, key = reading.get("sig"), _device_key(reading["compactor_id"])
    if not sig or not key:
        return None
    fill = reading.get("fill_pct")
    msg = "|".join([reading["compactor_id"], str(reading.get("seq")), str(int(ts.timestamp())) if ts_given else "-",
                    f"{reading['weight_kg']:.1f}", f"{fill:.1f}" if fill is not None else "-"])
    good = hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, str(sig).lower())


def ingest(reading: dict) -> dict:
    """Store one reading and return {"reading_id", "alerts", "status"}. Raises KeyError if unknown compactor."""
    engine = get_engine()
    ts_given = reading.get("ts") is not None
    ts = _utc(reading.get("ts"))
    verified = verify_signature(reading, ts_given, ts)
    edge = reading.get("edge") or {}

    with engine.begin() as conn:
        comp = conn.execute(select(compactors).where(compactors.c.id == reading["compactor_id"])).mappings().first()
        if comp is None:
            raise KeyError(reading["compactor_id"])
        mat = conn.execute(select(materials).where(materials.c.name == comp["material"])).mappings().first()

        history = conn.execute(
            select(readings.c.ts, readings.c.weight_kg, readings.c.fill_pct)
            .where(readings.c.compactor_id == comp["id"], readings.c.ts < ts)
            .order_by(readings.c.ts.desc()).limit(HISTORY_SIZE)
        ).mappings().all()
        history = [dict(h) for h in reversed(history)]

        # the same message twice (network retry, MQTT QoS 1): store it once, no new alerts
        dup = conn.execute(select(readings.c.id).where(readings.c.compactor_id == comp["id"], readings.c.ts == ts)).first()
        if dup is not None:
            st = conn.execute(select(compactor_status).where(compactor_status.c.compactor_id == comp["id"])).mappings().first()
            return {"reading_id": dup[0], "alerts": [], "duplicate": True, "commands": [],
                    "status": {**(dict(st) if st else {"compactor_id": comp["id"]}), "name": comp["name"], "material": comp["material"]}}

        new = {"weight_kg": reading["weight_kg"], "fill_pct": reading.get("fill_pct")}
        for h in history:
            h["ts"] = _utc(h["ts"])
        found = anomaly.check(new, history, dict(comp), dict(mat), ts=ts)

        # ML models from models/ (skip if the reading is clearly broken)
        plausible = [h for h in history if -20 <= h["weight_kg"] <= comp["capacity_kg"] * 1.3]
        if not any(a["type"] == "sensor_fault" and a["severity"] == "critical" for a in found):
            prev_w = plausible[-1]["weight_kg"] if plausible else None
            feats = features.make_features(new["weight_kg"], new["fill_pct"], prev_w, dict(comp), dict(mat))
            found += ml.check(feats)

        # LIVE LIFT MODEL: when the container was just emptied, judge the lift (too early? too late?)
        if any(a["type"] == "emptied" for a in found) and plausible:
            window = [dict(r) for r in conn.execute(
                select(readings.c.ts, readings.c.weight_kg, readings.c.fill_pct)
                .where(readings.c.compactor_id == comp["id"], readings.c.ts < ts,
                       readings.c.ts >= ts - timedelta(hours=72 / pickups.SCALE))
                .order_by(readings.c.ts)).mappings()]
            for r in window:
                r["ts"] = _stretch(_utc(r["ts"]), ts)
            last = conn.execute(
                select(alerts.c.ts).where(alerts.c.compactor_id == comp["id"], alerts.c.type == "emptied", alerts.c.ts < ts)
                .order_by(alerts.c.ts.desc()).limit(1)).first()
            before = {**plausible[-1], "ts": _stretch(_utc(plausible[-1]["ts"]), ts)}
            raw = live_lift.build_raw(ts, before, window, _stretch(_utc(last[0]), ts) if last else None, dict(comp))
            found += ml.check_lift(raw)

        # edge node: proof of origin, and readings that waited in the board's offline buffer
        if verified is False:
            found.append({"type": "signature_invalid", "severity": "critical",
                          "message": "Signature does not match: this reading was changed after the device sent it, "
                                     "or the device key is wrong. Do not use it as evidence."})
        if edge.get("from_buffer"):
            late = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            found.append({"type": "edge_buffered", "severity": "info",
                          "message": f"Delivered from the device's offline buffer, {late:.0f} min after it was measured"})

        reading_id = conn.execute(
            insert(readings).values(compactor_id=comp["id"], ts=ts, verified=verified, **new,
                                   seq=reading.get("seq"), edge_quality=edge.get("quality"),
                                   spikes_filtered=edge.get("spikes_filtered"),
                                   from_buffer=edge.get("from_buffer") if edge else None)
        ).inserted_primary_key[0]

        # --- status ---
        load = _load_pct(new["weight_kg"], new["fill_pct"], comp["capacity_kg"])
        if load >= 90 and not any(a["type"] == "emptied" for a in found):
            prev_load = _load_pct(history[-1]["weight_kg"], history[-1]["fill_pct"], comp["capacity_kg"]) if history else 0
            if prev_load < 90:  # only alert once when crossing 90%
                found.append({"type": "nearly_full", "severity": "info", "message": f"Compactor is {load:.0f}% full — book a pickup"})

        # points since last emptying, for the forecast
        cycle = []
        for h in history + [{**new, "ts": ts}]:
            pct = _load_pct(h["weight_kg"], h["fill_pct"], comp["capacity_kg"])
            if cycle and pct < cycle[-1][1] - 30:  # big drop = emptied -> new cycle
                cycle = []
            cycle.append((_stretch(_utc(h["ts"]), ts), pct))

        density = anomaly.calc_density(new["weight_kg"], new["fill_pct"], comp["volume_m3"])
        status = {
            "compactor_id": comp["id"],
            "weight_kg": round(new["weight_kg"], 1),
            "fill_pct": new["fill_pct"],
            "load_pct": load,
            "density_kg_m3": round(density, 1) if density else None,
            **value.material_value(new["weight_kg"], dict(mat)),
            "hours_to_full": forecast.hours_to_full(cycle, load),
            "last_ts": ts,
        }
        # --- pickups: book trucks, send them to the board, judge every lift, price it, check the invoice ---
        emptied = any(a["type"] == "emptied" for a in found) or bool(edge.get("emptied"))
        before = ({**plausible[-1], "after_kg": new["weight_kg"]} if plausible else None)
        if not emptied and before and pickups.truck_emptied(conn, comp["id"], before["weight_kg"], new["weight_kg"], comp["capacity_kg"]):
            emptied = True     # our truck emptied an almost-empty container: close the pickup, it was no "unexpected" drop
            found = [a for a in found if a["type"] != "unexpected_drop"]
            found.append({"type": "emptied", "severity": "info", "message": f"Emptied by the truck: {before['weight_kg']:.0f} kg collected"})
        p_alerts, commands = pickups.tick(conn, dict(comp), dict(mat), ts, load, emptied, before)
        found += p_alerts
        # the AI lift model is a SECOND OPINION: where it contradicts the board's measurement (e.g. "came late" for a
        # lift at 36 %), the measurement wins -> keep it (model monitoring counts it) but as info, never as a problem
        verdict = next((a["type"] for a in p_alerts if a["type"] in ("pickup_on_time", "pickup_too_early", "pickup_too_late")), None)
        agrees = {"ml_delayed_collection": "pickup_too_late", "ml_premature_unjustified": "pickup_too_early"}
        for a in found:
            if verdict and a["type"] in agrees and agrees[a["type"]] != verdict:
                a["severity"] = "info"
                a["message"] = "AI second opinion, the measurement disagrees: " + a["message"]

        conn.execute(delete(compactor_status).where(compactor_status.c.compactor_id == comp["id"]))
        conn.execute(insert(compactor_status).values(**status))

        saved = []
        for a in found:
            aid = conn.execute(insert(alerts).values(compactor_id=comp["id"], ts=ts, **a)).inserted_primary_key[0]
            saved.append({"id": aid, "compactor_id": comp["id"], "ts": ts, **a})

    return {"reading_id": reading_id, "alerts": saved, "commands": commands,
            "status": {**status, "name": comp["name"], "material": comp["material"]}}


def get_status(compactor_id=None) -> list[dict]:
    q = (select(compactors.c.id.label("compactor_id"), compactors.c.name, compactors.c.material,
                *[c for c in compactor_status.c if c.name != "compactor_id"])
         .select_from(compactors.outerjoin(compactor_status, compactors.c.id == compactor_status.c.compactor_id))
         .order_by(compactors.c.id))
    if compactor_id:
        q = q.where(compactors.c.id == compactor_id)
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]
