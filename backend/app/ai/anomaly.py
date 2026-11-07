"""Anomaly detection. Owner: AI person.

check() gets the new reading + recent history and returns a list of alerts.
Start: simple rules + statistics. Later: train a model (e.g. IsolationForest) on collected data.
"""
from statistics import mean, pstdev


def check(new: dict, history: list[dict], compactor: dict, material: dict) -> list[dict]:
    """
    new:       {"weight_kg", "fill_pct"}  (fill_pct may be None)
    history:   previous readings, oldest first, same keys
    compactor: row from compactors table
    material:  row from materials table
    returns:   [{"type", "severity", "message"}]
    """
    alerts = []
    w = new["weight_kg"]
    cap = compactor["capacity_kg"]

    # 1. Impossible values -> sensor problem
    if w < -20 or w > cap * 1.3:
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
        # light material: little weight but the fill sensor clearly drops from full-ish to empty
        by_fill = prev_fill is not None and fill is not None and prev_fill >= 30 and fill <= 10 and w < prev * 0.5
        # one bad weight reading while the fill sensor still says "well filled" is a glitch, not an emptying
        glitch = fill is not None and fill >= 30
        if (by_weight or by_fill) and not glitch:
            alerts.append(_a("emptied", "info", f"Emptied: {prev:.0f} kg collected"))

        # 3. Weight dropped but not emptied -> strange (sensor drift, theft, leak)
        elif delta < -max(30, prev * 0.15):
            alerts.append(_a("unexpected_drop", "warning", f"Weight dropped {abs(delta):.0f} kg without emptying"))

        # 4. Sudden jump much bigger than normal increases (z-score on recent deltas)
        deltas = [b["weight_kg"] - a["weight_kg"] for a, b in zip(history, history[1:])]
        ups = [d for d in deltas if d > 0]
        if len(ups) >= 5:
            mu, sd = mean(ups), pstdev(ups) or 1.0
            limit = max(mu + 5 * sd, 50)
            if delta > limit:
                alerts.append(_a("spike", "warning", f"Sudden +{delta:.0f} kg (normal up to ~{limit:.0f} kg)"))

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
