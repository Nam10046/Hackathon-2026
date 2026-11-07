"""Anomaly detection. Owner: AI person.

check() gets the new reading + recent history and returns a list of alerts.
Start: simple rules + statistics. Later: train a model (e.g. IsolationForest) on collected data.
"""
import os
from statistics import mean, pstdev

# Tuned with the simulator (simulator/simulate.py), which knows the right answers for each kind of bad data.
NOISE_KG = float(os.getenv("WEIGHT_NOISE_KG", "15"))          # 1 sigma of one reading (dataset: 15 kg)
READING_INTERVAL_H = float(os.getenv("READING_INTERVAL_H", "1"))
GAP_FACTOR = 3                                                 # no reading for 3 intervals -> data gap
STUCK_READINGS = 6                                             # 6 identical readings in a row -> stuck sensor


def check(new: dict, history: list[dict], compactor: dict, material: dict, ts=None) -> list[dict]:
    """
    new:       {"weight_kg", "fill_pct"}  (fill_pct may be None)
    history:   previous readings, oldest first, same keys (+ "ts")
    compactor: row from compactors table
    material:  row from materials table
    ts:        time of the new reading (for gap detection)
    returns:   [{"type", "severity", "message"}]
    """
    alerts = []
    w = new["weight_kg"]
    cap = compactor["capacity_kg"]

    # 0. Data gap: the device was silent (power, network, broken node). Said once, on the first reading back.
    if ts is not None and history and history[-1].get("ts") is not None:
        last = history[-1]["ts"]
        last = last if last.tzinfo or ts.tzinfo is None else last.replace(tzinfo=ts.tzinfo)
        gap_h = (ts - last).total_seconds() / 3600
        if gap_h > GAP_FACTOR * READING_INTERVAL_H:
            gap = f"{gap_h:.0f} h" if gap_h >= 1 else f"{gap_h * 60:.0f} min"
            alerts.append(_a("data_gap", "warning", f"No data for {gap} — node offline, or the server could not receive"))

    # 1. Impossible values -> sensor problem (a few kg below zero is normal noise on an empty scale)
    if w < -max(20, 4 * NOISE_KG) or w > cap * 1.3:
        alerts.append(_a("sensor_fault", "critical", f"Impossible weight {w:.0f} kg (capacity {cap:.0f} kg)"))
        return alerts  # other checks make no sense on a broken value

    # ignore earlier broken readings so one glitch doesn't cause false alerts later
    history = [h for h in history if -20 <= h["weight_kg"] <= cap * 1.3]

    if history:
        prev = history[-1]["weight_kg"]
        delta = w - prev

        # 2. Weight went to ~0 -> compactor was emptied (normal event).
        #    Low threshold on purpose: an EARLY (half-empty) lift is still a lift, and the lift model must see it.
        prev_fill, fill = history[-1].get("fill_pct"), new.get("fill_pct")
        # a real drop, not sensor noise around empty (e.g. 75 kg -> 25 kg on a 735 kg container)
        by_weight = prev >= cap * 0.10 and w < cap * 0.05 and prev - w >= cap * 0.08
        # the fill sensor clearly drops to empty and the weight falls a lot. Also catches low-fill lifts and lifts
        # on a scale whose zero has drifted (the weight then never gets near 0)
        by_fill = (prev_fill is not None and fill is not None and prev_fill >= 15 and fill <= 8
                   and prev - w >= max(4 * NOISE_KG, cap * 0.05))
        # one bad weight reading while the fill sensor still says "well filled" is a glitch, not an emptying
        glitch = fill is not None and fill >= 30
        if (by_weight or by_fill) and not glitch:
            alerts.append(_a("emptied", "info", f"Emptied: {prev:.0f} kg collected"))
            # an empty container must read about zero; if not, the zero has shifted (drift) or residue stayed inside
            if w > max(100, cap * 0.04):          # an hour of new waste after the truck left is normal
                alerts.append(_a("zero_shift", "warning", f"Empty container still reads {w:.0f} kg — scale zero drifted "
                                                          "or residue left inside; check before trusting the next weights"))

        # 3. Weight dropped but not emptied -> strange (sensor drift, theft, leak).
        #    Two readings differ by ~1.4 x NOISE_KG just from noise, so ask for a clear drop
        elif delta < -max(6 * NOISE_KG, prev * 0.15):
            alerts.append(_a("unexpected_drop", "warning", f"Weight dropped {abs(delta):.0f} kg without emptying"))

        # 4. Sudden jump much bigger than normal increases. Busy hours add more than quiet ones, so the limit is
        #    2.5 x the usual big increase (90th percentile), never below 6 noise-sigmas. Skipped after a data gap
        #    (hours of filling arrive in one step) and right after an emptying.
        deltas = [b["weight_kg"] - a["weight_kg"] for a, b in zip(history, history[1:])]
        ups = sorted(d for d in deltas if d > 0)
        gap = any(a["type"] == "data_gap" for a in alerts)
        if len(ups) >= 5 and not gap:
            mu, sd = mean(ups), pstdev(ups) or 1.0
            p90 = ups[int(0.9 * (len(ups) - 1))]
            limit = max(mu + 5 * sd, 2.5 * p90, 6 * NOISE_KG)
            if delta > limit:
                alerts.append(_a("spike", "warning", f"Sudden +{delta:.0f} kg (normal up to ~{limit:.0f} kg)"))

        # 4c. Heavier than the container may carry: wrong/wet material, or the truck cannot lift it legally
        if w > cap * 1.05 >= prev:
            alerts.append(_a("overload", "warning", f"{w:.0f} kg is above the rated payload ({cap:.0f} kg) — heavy or wrong "
                                                    "material; the truck may not be allowed to lift it"))

    # 4b. Stuck sensor: real readings always wobble a little; the exact same values again and again = frozen sensor/ADC
    run = history[-(STUCK_READINGS - 1):]
    if (len(run) == STUCK_READINGS - 1 and all(h["weight_kg"] == w and h.get("fill_pct") == new.get("fill_pct") for h in run)
            and not (len(history) >= STUCK_READINGS and history[-STUCK_READINGS]["weight_kg"] == w
                     and history[-STUCK_READINGS].get("fill_pct") == new.get("fill_pct"))):
        alerts.append(_a("sensor_stuck", "warning", f"Same reading ({w:.0f} kg) {STUCK_READINGS} times in a row — sensor may be frozen"))

    # 5. Density check -> wrong or wet material lowers recycling value
    #    Alert only when the problem STARTS (previous reading was normal), not on every reading
    lo, hi = material["density_min"], material["density_max"]
    density = calc_density(w, new.get("fill_pct"), compactor["volume_m3"])
    prev_density = None
    if history:
        prev_density = calc_density(history[-1]["weight_kg"], history[-1].get("fill_pct"), compactor["volume_m3"])
    prev_high = prev_density is not None and prev_density > hi
    prev_low = prev_density is not None and prev_density < lo * 0.5

    if density is not None:
        if density > hi and not prev_high:
            alerts.append(_a("contamination", "warning",
                             f"Density {density:.0f} kg/m³ is above normal for {material['name']} ({lo:.0f}–{hi:.0f})"))
        elif density < lo * 0.5 and not prev_low:
            alerts.append(_a("sensor_fault", "warning",
                             f"Density {density:.0f} kg/m³ is very low — check fill or weight sensor"))

    return alerts


def calc_density(weight_kg: float, fill_pct, volume_m3: float):
    """kg per m3 of the filled part. None if we can't tell (no fill data or almost empty)."""
    if fill_pct is None or fill_pct < 20 or weight_kg <= 0:
        return None
    return weight_kg / (fill_pct / 100 * volume_m3)


def _a(type_, severity, message):
    return {"type": type_, "severity": severity, "message": message}
