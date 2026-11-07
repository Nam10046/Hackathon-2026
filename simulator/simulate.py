"""Compactor SIMULATOR with known answers, to grade the live system. Owner: AI / backend person.

    python simulator/simulate.py grade                 # 24 compactors x 75 days, prints the scorecard (~3 min)
    python simulator/simulate.py grade --devices 8 --days 30 --seed 2
    python simulator/simulate.py live --api http://localhost:8000 --hours 72 --speed 60
                                                       # sends C1-C3 readings to the running backend (Grafana "Live sensors")

What it does
  1. Builds a small world: compactors fill up during working hours and get emptied. Every emptying is one of
       NORMAL     emptied at 70-92 % full
       PREMATURE  emptied at 12-38 % full, no hygiene reason            -> should get ml_premature_unjustified
       JUSTIFIED  low fill, but the hygiene maximum (days) is reached   -> must NOT be flagged (a trap)
       DELAYED    sat >= 97 % full for 28-80 hours before the truck came -> should get ml_delayed_collection
  2. Adds BAD DATA with known answers: spikes, impossible values, a stuck sensor, missing hours, slow drift,
     a single glitch reading, duplicate messages and a contaminated (too dense) load.
  3. Sends every reading, one by one, through the REAL backend code (backend/app/service.ingest), exactly as an
     ESP32 / SMART controller would, into a throw-away SQLite database.
  4. Compares the backend's alerts with the answers and prints a scorecard (0-100) per part.

Honesty rule: this is OUR world and OUR definitions. We use it to find weak spots in the live pipeline (robustness).
We never train the model on it. The model's accuracy number stays the one measured on the Europress dataset.
Physics are simplified (straight-line filling, hourly readings, 15 kg weight noise like the dataset).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)          # a Monday
MATERIALS = {"cardboard": (2000, 8), "plastic": (1500, 8), "mixed": (4000, 8)}   # capacity kg, volume m3 (= backend seed)
MAX_DAYS = {"cardboard": 28, "plastic": 28, "mixed": 21}         # hygiene maximum, same as backend live_lift.MAX_DAYS
NOISE_KG, FILL_NOISE = 15.0, 1.5                                  # 1 sigma, like the dataset's mass_uncertainty_kg
LIFT_MIX = {"NORMAL": 0.55, "PREMATURE": 0.15, "DELAYED": 0.18, "JUSTIFIED": 0.12}
FAULTS = ["SPIKE", "IMPOSSIBLE", "STUCK", "GAP", "DRIFT", "GLITCH", "DUPLICATE", "CONTAMINATION"]
# which alert types count as "the system noticed this fault"
EXPECT = {"SPIKE": {"spike", "sensor_fault"}, "IMPOSSIBLE": {"sensor_fault"}, "STUCK": {"sensor_stuck"},
          "GAP": {"data_gap"}, "DRIFT": {"zero_shift"}, "CONTAMINATION": {"contamination", "overload"}}
WARNING_TYPES = {"sensor_fault", "spike", "unexpected_drop", "contamination", "sensor_stuck", "data_gap", "zero_shift", "overload"}


@dataclass
class Device:
    id: str
    material: str
    capacity: float
    volume: float
    daily_pct: float                                   # fill % per working day
    readings: list = field(default_factory=list)       # dicts: ts, weight_kg, fill_pct (as sent)
    lifts: list = field(default_factory=list)          # truth: {"at", "kind", "fill_before"}
    faults: list = field(default_factory=list)         # truth: {"kind", "start", "end"}


def working(ts: datetime) -> bool:
    return ts.weekday() < 6 and 7 <= ts.hour < 19


def build_world(n_devices: int, days: int, seed: int) -> list[Device]:
    rnd = random.Random(seed)
    devs = []
    for i in range(n_devices):
        mat = ["cardboard", "plastic", "mixed"][i % 3]
        cap, vol = MATERIALS[mat]
        d = Device(f"SIM-{i + 1:02d}", mat, cap, vol, daily_pct=rnd.uniform(9, 24))
        simulate_device(d, days, rnd)
        add_faults(d, rnd)
        devs.append(d)
    return devs


def simulate_device(d: Device, days: int, rnd: random.Random):
    """True mass hour by hour, with lifts decided by the scenario of each cycle."""
    hours = days * 24
    mass, last_lift_h, hold, over80 = rnd.uniform(0, 0.2) * d.capacity, None, 0, 0
    kind, target, pending_lift_h, rate_override = "NORMAL", 0.8, None, None
    next_cycle = lambda: rnd.choices(list(LIFT_MIX), weights=list(LIFT_MIX.values()))[0]  # noqa: E731
    target = rnd.uniform(0.70, 0.92)
    for h in range(hours):
        ts = START + timedelta(hours=h)
        # ---- filling ----
        if rate_override is not None:                    # slow JUSTIFIED cycle
            rate = rate_override
        elif working(ts):
            rate = d.daily_pct / 100 * d.capacity / 12
        else:
            rate = 0.0
        mass = min(d.capacity, mass + rate * rnd.uniform(0.6, 1.4))
        fill = mass / d.capacity
        over80 += fill >= 0.80
        hrs_since = (h - last_lift_h) if last_lift_h is not None else h + 24 * 7
        # ---- decide the lift of this cycle ----
        if pending_lift_h is None:
            if kind == "DELAYED":
                if fill >= 0.97:
                    hold += 1
                    if hold >= target:
                        pending_lift_h = h
            elif kind == "JUSTIFIED":
                if hrs_since >= MAX_DAYS[d.material] * 24 + rnd.randint(0, 4):
                    pending_lift_h = h
            elif fill >= target:
                pending_lift_h = h + (rnd.randint(1, 5) if kind == "NORMAL" else 0)
        # ---- the reading at this hour (taken a few minutes after the hour) ----
        rts = ts + timedelta(minutes=rnd.randint(0, 5))
        if pending_lift_h is not None and h >= pending_lift_h and 6 <= ts.hour < 18:
            # truck comes between this hour and the next reading
            d.lifts.append({"at": rts + timedelta(minutes=20), "kind": kind, "fill_before": round(fill * 100, 1),
                            "hours_since": hrs_since, "hours_over_80": over80})
            d.readings.append(_reading(rts, mass, fill, rnd))
            mass, last_lift_h, hold, pending_lift_h, rate_override, over80 = rnd.uniform(0, 25), h, 0, None, None, 0
            kind = next_cycle()
            if kind == "PREMATURE":
                target = rnd.uniform(0.12, 0.38)
            elif kind == "DELAYED":
                target = rnd.randint(28, 80)             # hours spent full
            elif kind == "JUSTIFIED":
                # slow cycle: only 15-35 % full when the hygiene maximum is reached
                tgt = rnd.uniform(0.15, 0.35) * d.capacity
                rate_override = tgt / (MAX_DAYS[d.material] * 24)
            else:
                target = rnd.uniform(0.70, 0.92)
            continue
        d.readings.append(_reading(rts, mass, fill, rnd))


def _reading(ts, mass, fill, rnd):
    return {"ts": ts, "weight_kg": round(mass + rnd.gauss(0, NOISE_KG), 1),
            "fill_pct": round(min(100, max(0, fill * 100 + rnd.gauss(0, FILL_NOISE))), 1)}


def add_faults(d: Device, rnd: random.Random):
    """Inject bad data away from lifts (so each answer is clear)."""
    lift_times = [l["at"] for l in d.lifts]
    near_lift = lambda a, b: any(a - timedelta(hours=8) <= t <= b + timedelta(hours=8) for t in lift_times)  # noqa: E731
    n = max(3, int(len(d.readings) / 24 / 60 * 6))           # ~6 faults per device per 60 days
    kinds = rnd.sample(FAULTS, len(FAULTS)) + [rnd.choice(FAULTS) for _ in range(max(0, n - len(FAULTS)))]
    taken = set()
    for kind in kinds:
        for _ in range(40):                                   # find a free spot
            n_r = len(d.readings)
            i = rnd.randrange(min(48, n_r // 5), n_r - min(100, n_r // 4))
            length = {"STUCK": rnd.randint(8, 20), "GAP": rnd.randint(4, 12), "DRIFT": 1,
                      "CONTAMINATION": 36}.get(kind, 1)
            span = range(i - 2, i + length + 2)
            a, b = d.readings[i]["ts"], d.readings[min(len(d.readings) - 1, i + length)]["ts"]
            if any(j in taken for j in span) or (kind != "DRIFT" and near_lift(a, b)):
                continue
            if kind in ("SPIKE", "GLITCH", "STUCK", "CONTAMINATION") and d.readings[i]["fill_pct"] < 35:
                continue                                      # visible faults need a partly full container
            break
        else:
            continue
        taken.update(span)
        r = d.readings
        if kind == "SPIKE":
            r[i]["weight_kg"] = round(min(1.25 * d.capacity, r[i]["weight_kg"] + rnd.uniform(0.35, 0.6) * d.capacity), 1)
            end = r[i]["ts"]
        elif kind == "IMPOSSIBLE":
            r[i]["weight_kg"] = rnd.choice([-150.0, round(1.6 * d.capacity, 1)])
            end = r[i]["ts"]
        elif kind == "GLITCH":
            r[i]["weight_kg"] = round(rnd.uniform(0, 0.03) * d.capacity, 1)
            end = r[i]["ts"]
        elif kind == "STUCK":
            for j in range(i + 1, i + length):
                r[j]["weight_kg"], r[j]["fill_pct"] = r[i]["weight_kg"], r[i]["fill_pct"]
            end = r[i + length - 1]["ts"]
        elif kind == "GAP":
            end = r[i + length]["ts"]
            for j in range(i, i + length):
                r[j]["drop"] = True
        elif kind == "DUPLICATE":
            r[i]["dup"] = True
            end = r[i]["ts"]
        elif kind == "CONTAMINATION":
            # heavy/wet material (e.g. wet cardboard, rubble in mixed waste): weight rises to ~2x what the fill level
            # suggests within 12 h and stays there for the rest of the 36 h window
            for j in range(i, i + length):
                k = 1 + min(1.0, (j - i + 1) / 12)
                r[j]["weight_kg"] = round(min(1.25 * d.capacity, r[j]["weight_kg"] * k), 1)
            end = r[i + length - 1]["ts"]
        elif kind == "DRIFT":
            # load cell drifts +3 kg/h for 3 days; only visible when the frame should read ~0 after the next lift
            nxt = next((t for t in lift_times if t > r[i]["ts"] + timedelta(hours=72)), None)
            if nxt is None:
                continue
            stop = nxt + timedelta(hours=24)                  # recalibrated a day after the lift
            for j in range(i, len(r)):
                if r[j]["ts"] > stop:
                    break
                r[j]["weight_kg"] = round(r[j]["weight_kg"] + min(72, (r[j]["ts"] - r[i]["ts"]).total_seconds() / 3600) * 3, 1)
            end = nxt + timedelta(hours=6)                    # we expect the alert right after the lift
            d.faults.append({"kind": kind, "start": r[i]["ts"], "end": end, "quiet_until": stop + timedelta(hours=2)})
            continue
        d.faults.append({"kind": kind, "start": r[i]["ts"], "end": end})


# ------------------------------------------------------------------ run through the real backend
def run_backend(devs: list[Device]):
    db = Path(tempfile.gettempdir()) / "simulator_grade.db"
    if db.exists():
        db.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db}"
    os.environ["MODELS_DIR"] = str(ROOT / "models")
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlalchemy import insert, select
    from app import service
    from app.ai import ml
    from app.db import alerts, compactors, get_engine, init_db, readings
    init_db()
    ml.load_all()
    eng = get_engine()
    with eng.begin() as conn:
        for d in devs:
            conn.execute(insert(compactors).values(id=d.id, name=d.id, material=d.material, capacity_kg=d.capacity,
                                                   volume_m3=d.volume, on_call_threshold_pct=80))
    t0, n = time.time(), 0
    for d in devs:
        for r in d.readings:
            if r.get("drop"):
                continue
            body = {"compactor_id": d.id, "ts": r["ts"], "weight_kg": r["weight_kg"], "fill_pct": r["fill_pct"]}
            service.ingest(dict(body))
            n += 1
            if r.get("dup"):
                service.ingest(dict(body))                     # the same message arrives twice
                n += 1
        print(f"  {d.id}: done ({n} messages, {time.time() - t0:.0f} s)", flush=True)
    with eng.connect() as conn:
        al = [dict(x) for x in conn.execute(select(alerts.c.compactor_id, alerts.c.ts, alerts.c.type)).mappings()]
        stored = Counter(c for (c,) in conn.execute(select(readings.c.compactor_id)))
        per_ts = Counter((c, t if t.tzinfo else t.replace(tzinfo=timezone.utc))
                         for c, t in conn.execute(select(readings.c.compactor_id, readings.c.ts)))
    stored = (stored, per_ts)
    for a in al:
        a["ts"] = a["ts"] if a["ts"].tzinfo else a["ts"].replace(tzinfo=timezone.utc)
    return al, stored, n


# ------------------------------------------------------------------ grading
def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def grade(devs: list[Device], al: list[dict], stored_info) -> dict:
    stored, per_ts = stored_info
    by_dev = defaultdict(list)
    for a in al:
        by_dev[a["compactor_id"]].append(a)
    lift_tp = lift_fn = lift_fp = 0
    cls = {"PREMATURE": Counter(), "DELAYED": Counter(), "DELAYED_ONCALL": Counter()}
    trap = Counter()
    confusion = Counter()                                 # (truth kind, flags) -> count, to see WHAT gets confused
    examples = defaultdict(list)
    fault_hits = defaultdict(Counter)
    false_alarms = Counter()
    dup_alerts = 0
    for d in devs:
        A = sorted(by_dev[d.id], key=lambda a: a["ts"])
        emptied = [a for a in A if a["type"] == "emptied"]
        used = set()
        for l in d.lifts:
            m = [e for e in emptied if l["at"] - timedelta(minutes=30) <= e["ts"] <= l["at"] + timedelta(hours=3)
                 and id(e) not in used]
            if m:
                lift_tp += 1
                used.add(id(m[0]))
                flags = {a["type"] for a in A if a["ts"] == m[0]["ts"]}
            else:
                lift_fn += 1
                flags = set()
            pre, dly = "ml_premature_unjustified" in flags, "ml_delayed_collection" in flags
            confusion[(l["kind"], "early" if pre else "late" if dly else "ok" if flags or m else "not seen")] += 1
            if (dly and l["kind"] != "DELAYED") or (pre and l["kind"] != "PREMATURE"):
                examples["late" if dly else "early"].append({"truth": l["kind"], "fill_before": l["fill_before"],
                                                             "hours_since_last": l["hours_since"]})
            for fam, hit in (("PREMATURE", pre), ("DELAYED", dly), ("DELAYED_ONCALL", dly)):
                # on-call style (closer to the dataset's labels): lifted 24 h or more after passing the 80 % order level
                truth = (l["kind"] == "DELAYED" or l["hours_over_80"] >= 24) if fam == "DELAYED_ONCALL" else l["kind"] == fam
                cls[fam]["tp" if truth and hit else "fp" if hit else "fn" if truth else "tn"] += 1
            if l["kind"] == "JUSTIFIED":
                trap["flagged" if pre else "ok"] += 1
        glitch_ts = [f["start"] for f in d.faults if f["kind"] == "GLITCH"]
        lift_fp += sum(1 for e in emptied if id(e) not in used)
        for f in d.faults:
            win = [a for a in A if f["start"] - timedelta(minutes=10) <= a["ts"] <= f["end"] + timedelta(hours=2)]
            if f["kind"] == "GLITCH":
                ok = not any(a["type"] == "emptied" for a in win)
            elif f["kind"] == "DUPLICATE":
                same_ts = [a for a in A if a["ts"] == f["start"]]
                ok = len(same_ts) == len({a["type"] for a in same_ts}) and per_ts[(d.id, f["start"])] <= 1
                dup_alerts += len(same_ts) - len({a["type"] for a in same_ts})
            else:
                ok = any(a["type"] in EXPECT[f["kind"]] for a in win)
            fault_hits[f["kind"]]["found" if ok else "missed"] += 1
        # the technician's recalibration after a drift is a real, logged event: not counted as a false alarm
        windows = [(f["start"] - timedelta(hours=1), f.get("quiet_until", f["end"]) + timedelta(hours=3)) for f in d.faults]
        for a in A:
            if a["type"] in WARNING_TYPES and not any(s <= a["ts"] <= e for s, e in windows):
                false_alarms[a["type"]] += 1
    device_weeks = sum((d.readings[-1]["ts"] - d.readings[0]["ts"]).days for d in devs) / 7
    expected_msgs = sum(1 for d in devs for r in d.readings if not r.get("drop"))
    res = {
        "lift_detection": prf(lift_tp, lift_fp, lift_fn),
        "premature": prf(cls["PREMATURE"]["tp"], cls["PREMATURE"]["fp"], cls["PREMATURE"]["fn"]),
        "delayed": prf(cls["DELAYED"]["tp"], cls["DELAYED"]["fp"], cls["DELAYED"]["fn"]),
        "delayed_oncall_definition": prf(cls["DELAYED_ONCALL"]["tp"], cls["DELAYED_ONCALL"]["fp"], cls["DELAYED_ONCALL"]["fn"]),
        "justified_trap": {"lifts": sum(trap.values()), "wrongly_flagged": trap["flagged"]},
        "confusion": {f"{k[0]} -> {k[1]}": v for k, v in sorted(confusion.items())},
        "wrong_flag_examples": {k: v[:12] for k, v in examples.items()},
        "faults": {k: dict(v) for k, v in sorted(fault_hits.items())},
        "false_alarms": {"total": sum(false_alarms.values()), "per_device_week": round(sum(false_alarms.values()) / device_weeks, 2),
                         "by_type": dict(false_alarms)},
        "duplicates": {"readings_stored_twice": int(sum(stored.values()) - expected_msgs), "duplicate_alerts": dup_alerts},
        "truth": {"devices": len(devs), "lifts": Counter(l["kind"] for d in devs for l in d.lifts),
                  "faults": Counter(f["kind"] for d in devs for f in d.faults), "device_weeks": round(device_weeks, 1)},
    }
    found = sum(v.get("found", 0) for v in fault_hits.values())
    total = sum(sum(v.values()) for v in fault_hits.values())
    res["fault_detection_rate"] = round(found / total, 3) if total else 1.0
    trap_ok = 1 - (trap["flagged"] / sum(trap.values()) if sum(trap.values()) else 0)
    fa_score = max(0.0, 1 - res["false_alarms"]["per_device_week"] / 1.0)   # 1 false alarm per device-week -> 0
    parts = {"Lift detection (F1)": (res["lift_detection"]["f1"], 25), "Too early (F1)": (res["premature"]["f1"], 15),
             "Too late (F1)": (res["delayed"]["f1"], 15), "Justified lifts left alone": (round(trap_ok, 3), 5),
             "Bad data noticed": (res["fault_detection_rate"], 25), "Few false alarms": (round(fa_score, 3), 15)}
    res["score_parts"] = {k: {"value": v, "weight": w} for k, (v, w) in parts.items()}
    res["score"] = round(sum(v * w for v, w in parts.values()), 1)
    return res


def print_report(res: dict):
    print("\n=== SIMULATOR SCORECARD (0-100) ===")
    for k, v in res["score_parts"].items():
        print(f"  {k:30s} {v['value']:.3f}  x {v['weight']:>2d} %")
    print(f"  {'TOTAL':30s} {res['score']}")
    t = res["truth"]
    print(f"\nworld: {t['devices']} compactors, {t['device_weeks']} device-weeks, lifts {dict(t['lifts'])}, faults {dict(t['faults'])}")
    for k in ("lift_detection", "premature", "delayed", "delayed_oncall_definition"):
        v = res[k]
        print(f"  {k:26s} precision {v['precision']:.3f} recall {v['recall']:.3f} F1 {v['f1']:.3f} (tp {v['tp']}, fp {v['fp']}, fn {v['fn']})")
    print(f"  justified lifts wrongly flagged: {res['justified_trap']['wrongly_flagged']} of {res['justified_trap']['lifts']}")
    print(f"  bad data: {res['faults']}")
    print(f"  false alarms: {res['false_alarms']}")
    print(f"  duplicates: {res['duplicates']}")


def cmd_grade(a):
    devs = build_world(a.devices, a.days, a.seed)
    print(f"world built: {len(devs)} compactors, {sum(len(d.readings) for d in devs)} readings, "
          f"{sum(len(d.lifts) for d in devs)} lifts, {sum(len(d.faults) for d in devs)} injected faults", flush=True)
    al, stored, n = run_backend(devs)
    res = grade(devs, al, stored)
    print_report(res)
    out = Path(a.out)
    out.write_text(json.dumps(res, indent=2, default=str))
    print(f"\nsaved {out}")


def cmd_live(a):
    """Send a short simulated history for the seeded compactors C1-C3 to a running backend, ending 'now'."""
    import urllib.request
    rnd = random.Random(a.seed)
    hours = a.hours
    devs = []
    for cid, mat in (("C1", "cardboard"), ("C2", "plastic"), ("C3", "mixed")):
        cap, vol = MATERIALS[mat]
        d = Device(cid, mat, cap, vol, daily_pct=rnd.uniform(18, 30))
        simulate_device(d, max(2, math.ceil(hours / 24)), rnd)
        add_faults(d, rnd) if a.faults else None
        devs.append(d)
    shift = datetime.now(timezone.utc) - (START + timedelta(hours=hours))
    msgs = sorted(((r["ts"] + shift, d.id, r) for d in devs for r in d.readings if not r.get("drop")
                   and r["ts"] < START + timedelta(hours=hours)), key=lambda x: x[0])
    headers = {"Content-Type": "application/json", **({"X-API-Key": a.key} if a.key else {})}
    print(f"sending {len(msgs)} readings to {a.api} ({a.speed} simulated hours per real second)")
    for i, (ts, cid, r) in enumerate(msgs):
        body = json.dumps({"compactor_id": cid, "ts": ts.isoformat(), "weight_kg": r["weight_kg"], "fill_pct": r["fill_pct"]}).encode()
        req = urllib.request.Request(a.api.rstrip("/") + "/api/readings", data=body, headers=headers, method="POST")
        res = json.loads(urllib.request.urlopen(req, timeout=10).read())
        for al in res.get("alerts", []):
            print(f"  {ts:%Y-%m-%d %H:%M} {cid} {al['type']}: {al['message']}")
        if a.speed and i % 3 == 2:
            time.sleep(1 / a.speed)
    print("done - open Grafana '6 Live sensors'")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--devices", type=int, default=24)
    g.add_argument("--days", type=int, default=75)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--out", default=str(ROOT / "simulator" / "scorecard.json"))
    l = sub.add_parser("live")
    l.add_argument("--api", default="http://localhost:8000")
    l.add_argument("--key", default=os.getenv("INGEST_API_KEY", ""))
    l.add_argument("--hours", type=int, default=72)
    l.add_argument("--speed", type=float, default=60, help="simulated hours sent per real second (0 = as fast as possible)")
    l.add_argument("--seed", type=int, default=7)
    l.add_argument("--faults", action="store_true", help="also inject bad data")
    a = ap.parse_args()
    cmd_grade(a) if a.cmd == "grade" else cmd_live(a)


if __name__ == "__main__":
    main()
