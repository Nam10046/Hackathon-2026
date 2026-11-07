"""LIVE TEST: play dataset sensor readings through the real backend, one reading at a time, like an ESP32 would.
Owner: AI / backend person.

    python training/replay_live.py --devices 40        # ~10 min, uses a throw-away SQLite database
    (stopped early? run the same command again — it continues where it stopped; --fresh starts over)

The backend only gets {compactor_id, ts, weight_kg, fill_pct} — no labels, no lift list, no order data. It must
  1. notice the emptying itself (rule "emptied" in backend/app/ai/anomaly.py),
  2. build the model inputs from its own reading history (backend/app/ai/live_lift.py),
  3. run the ESP32 lift models (models/*_esp32) and raise ml_premature_unjustified / ml_delayed_collection.
Afterwards we compare with the dataset's real lifts and answer labels (validation months only).
Output: training/replay_live_report.json + printed summary.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = Path(tempfile.gettempdir()) / "replay_live.db"
STATE = DB.with_suffix(".state.json")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["MODELS_DIR"] = str(ROOT / "models")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "training"))
from train_lift_model import FAMILIES, load_engine  # noqa: E402

WARMUP_DAYS = 10            # replay starts this long before the first lift (history for the 72 h window)
MATCH_BEFORE, MATCH_AFTER = timedelta(hours=2), timedelta(hours=4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=os.getenv("EUROPRESS_ENGINE", str(ROOT / "europress" / "Europress_SMART_Material_Value_Engine_v1.0.1")))
    ap.add_argument("--profile", default="competition")
    ap.add_argument("--devices", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-seconds", type=float, default=1e9, help="stop after this long; run again to continue")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    engine_dir = Path(a.engine)
    pub = engine_dir / "data" / a.profile / "public"
    dev_dir = pub / "labels_dev"
    _c, _cf, _dc, _di, _entity_times, _period_filter, _sb, open_dataset = load_engine(engine_dir)

    ent = _entity_times(dev_dir)
    va_ids = set(_period_filter(ent, dev_dir, "validation", "eval_at").entity_id)

    con = open_dataset(pub)
    lifts = con.sql("SELECT collection_id, device_id, actual_at FROM collection_events "
                    "WHERE status IN ('COMPLETED','PARTIAL')").df()
    devices = con.sql("SELECT * FROM devices WHERE has_weight_measurement").df()
    all_lifts = lifts.copy()
    lifts = lifts[lifts.collection_id.isin(va_ids) & lifts.device_id.isin(devices.device_id)]
    rng = np.random.default_rng(a.seed)
    pick = sorted(rng.choice(sorted(lifts.device_id.unique()), size=min(a.devices, lifts.device_id.nunique()), replace=False))
    lifts = lifts[lifts.device_id.isin(pick)].copy()
    lifts["actual_at"] = pd.to_datetime(lifts.actual_at, utc=True)
    # validation lifts are chosen by invoice date, so some happen in late May: start before the FIRST one
    lo, hi = lifts.actual_at.min() - pd.Timedelta(days=WARMUP_DAYS), lifts.actual_at.max() + pd.Timedelta(hours=6)
    ids = ",".join(f"'{d}'" for d in pick)
    tele = con.sql(f"""SELECT device_id, measured_at, mass_kg, fill_pct FROM telemetry_dedup
                       WHERE device_id IN ({ids}) AND mass_kg IS NOT NULL
                         AND measured_at >= '{(lo - pd.Timedelta(days=60)).isoformat()}' AND measured_at < '{hi.isoformat()}'
                       ORDER BY device_id, measured_at""").df()
    con.close()
    tele["measured_at"] = pd.to_datetime(tele.measured_at, utc=True)

    # backend database with these devices registered as compactors (resumes a stopped run)
    from sqlalchemy import insert, select
    from app.ai import ml
    from app.db import alerts, compactors, get_engine, init_db, materials
    from app import service
    state = json.loads(STATE.read_text()) if STATE.exists() and DB.exists() and not a.fresh else None
    if state is None or state["devices"] != pick:
        for f_ in (DB, STATE):
            if f_.exists():
                f_.unlink()
        state = {"devices": pick, "done": [], "readings": 0, "seconds": 0.0}
    init_db()
    print("models:", ml.load_all())
    eng = get_engine()
    if not state["done"]:
        with eng.begin() as conn:
            have = {r[0] for r in conn.execute(select(materials.c.name))}
            for m in devices[devices.device_id.isin(pick)].material_stream.unique():
                if m not in have:
                    conn.execute(insert(materials).values(name=m, price_eur_per_kg=0.0, density_min=0, density_max=10000, co2_factor=0))
            for d in devices[devices.device_id.isin(pick)].itertuples():
                past = tele[(tele.device_id == d.device_id) & (tele.measured_at < lo)].mass_kg
                cap = float(np.nanpercentile(past, 99)) if len(past) > 50 else float(tele[tele.device_id == d.device_id].mass_kg.max())
                thr = d.on_call_threshold_pct           # SMART setting (fill % that orders a truck)
                conn.execute(insert(compactors).values(id=d.device_id, name=d.device_id, material=d.material_stream,
                                                       capacity_kg=max(cap, 50.0), volume_m3=d.container_volume_m3,
                                                       on_call_threshold_pct=None if thr != thr else thr))

    replay = tele[tele.measured_at >= lo]
    t0 = time.time()
    for dev in pick:
        if dev in state["done"]:
            continue
        if time.time() - t0 > a.max_seconds:
            STATE.write_text(json.dumps(state))
            print(f"stopped: {len(state['done'])}/{len(pick)} devices done — run the same command again to continue")
            return
        part = replay[replay.device_id == dev]
        for r in part.itertuples(index=False):
            fill = None if pd.isna(r.fill_pct) else float(min(max(r.fill_pct, 0), 100))
            service.ingest({"compactor_id": r.device_id, "ts": r.measured_at.to_pydatetime(), "weight_kg": float(r.mass_kg), "fill_pct": fill})
        state["done"].append(dev)
        state["readings"] += len(part)
        print(f"  {len(state['done'])}/{len(pick)} devices · {time.time() - t0:.0f} s", flush=True)
    state["seconds"] += time.time() - t0
    STATE.write_text(json.dumps(state))
    print(f"replayed {state['readings']} readings from {len(pick)} devices")

    with eng.connect() as conn:
        al = pd.DataFrame(conn.execute(select(alerts.c.compactor_id, alerts.c.ts, alerts.c.type)).mappings().all())
    al["ts"] = pd.to_datetime(al.ts, utc=True)
    emptied = al[al.type == "emptied"]

    # match every real validation lift to the backend's own "emptied" alert
    lab = pd.read_parquet(dev_dir / "anomaly_labels.parquet")
    rows, used = [], set()
    for l in lifts.itertuples():
        e = emptied[(emptied.compactor_id == l.device_id) & (emptied.ts >= l.actual_at - MATCH_BEFORE)
                    & (emptied.ts <= l.actual_at + MATCH_AFTER)]
        ts = e.ts.min() if len(e) else None
        if ts is not None:
            used.add((l.device_id, ts))
        flags = set(al[(al.compactor_id == l.device_id) & (al.ts == ts)].type) if ts is not None else set()
        rows.append({"collection_id": l.collection_id, "seen": ts is not None, **{f: f"ml_{f.lower()}" in flags for f in FAMILIES}})
    res = pd.DataFrame(rows)
    in_window = emptied[(emptied.ts >= lifts.actual_at.min() - MATCH_BEFORE) & (emptied.ts <= lifts.actual_at.max() + MATCH_AFTER)]
    # an "emptied" alert is false only if NO real lift (any period, not only validation) is near it
    all_lifts["actual_at"] = pd.to_datetime(all_lifts.actual_at, utc=True)
    real = all_lifts[all_lifts.device_id.isin(pick)]
    extra = sum(not ((real.device_id == r.compactor_id) & (real.actual_at >= r.ts - MATCH_AFTER)
                     & (real.actual_at <= r.ts + MATCH_BEFORE)).any() for r in in_window.itertuples())

    report = {"devices": len(pick), "readings": int(state["readings"]), "real_lifts": int(len(res)),
              "lifts_noticed_by_backend": int(res.seen.sum()), "lift_detection_rate": round(float(res.seen.mean()), 3),
              "emptied_alerts_without_real_lift": int(extra), "families": {}}
    print(f"\nlifts noticed by the backend: {res.seen.sum()}/{len(res)} ({res.seen.mean():.1%}) · "
          f"'emptied' alerts with no real lift: {extra}")
    for fam in FAMILIES:
        y = res.collection_id.isin(set(lab[(lab.label_family == fam) & lab.is_actionable].entity_id)).to_numpy()
        flag = res[fam].to_numpy()
        tp, fp, fn = int((flag & y).sum()), int((flag & ~y).sum()), int((~flag & y).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        report["families"][fam] = {"real_problems": int(y.sum()), "flagged": int(flag.sum()), "caught": tp,
                                   "false_alarms": fp, "missed": fn, "precision": round(p, 3), "recall": round(rc, 3), "f1": round(f1, 3)}
        print(f"{fam:24s} precision {p:.3f} · recall {rc:.3f} · F1 {f1:.3f}  (caught {tp}, false alarms {fp}, missed {fn})")
    (ROOT / "training" / "replay_live_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
