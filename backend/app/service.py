"""Business logic: store a reading, run the AI parts, update status. Owner: backend person."""
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select

from app.ai import anomaly, forecast, value
from app.db import alerts, compactor_status, compactors, get_engine, materials, readings

HISTORY_SIZE = 50  # how many previous readings the AI looks at


def _utc(ts):
    """Make every timestamp timezone-aware UTC (SQLite returns naive ones)."""
    if ts is None:
        return datetime.now(timezone.utc)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _load_pct(weight_kg, fill_pct, capacity_kg):
    by_weight = max(weight_kg, 0) / capacity_kg * 100
    return round(max(by_weight, fill_pct or 0), 1)


def ingest(reading: dict) -> dict:
    """Store one reading and return {"reading_id", "alerts", "status"}. Raises KeyError if unknown compactor."""
    engine = get_engine()
    ts = _utc(reading.get("ts"))

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

        new = {"weight_kg": reading["weight_kg"], "fill_pct": reading.get("fill_pct")}
        found = anomaly.check(new, history, dict(comp), dict(mat))

        reading_id = conn.execute(
            insert(readings).values(compactor_id=comp["id"], ts=ts, **new)
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
            cycle.append((_utc(h["ts"]), pct))

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
        conn.execute(delete(compactor_status).where(compactor_status.c.compactor_id == comp["id"]))
        conn.execute(insert(compactor_status).values(**status))

        saved = []
        for a in found:
            aid = conn.execute(insert(alerts).values(compactor_id=comp["id"], ts=ts, **a)).inserted_primary_key[0]
            saved.append({"id": aid, "compactor_id": comp["id"], "ts": ts, **a})

    return {"reading_id": reading_id, "alerts": saved,
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
