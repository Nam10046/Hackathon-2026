"""Build the live lift-model input from a compactor's own reading history. Owner: AI / backend person.

Called by the backend when it sees an emptying (weight drops to ~0). Uses the same feature definition as
training (lift_features.py). Things a simple ESP32 node does not send (press load, cycles, schedule, trigger)
stay unknown — the model was trained to handle missing values.
"""
from datetime import timedelta

# our demo compactors use short material names; the model knows the Europress names
MATERIAL_MAP = {"cardboard": "cardboard", "plastic": "plastic_film", "mixed": "mixed_waste",
                "paper": "paper", "biowaste": "biowaste", "mixed_plastic": "mixed_plastic",
                "plastic_film": "plastic_film", "mixed_waste": "mixed_waste"}
MAX_DAYS = {"cardboard": 28, "paper": 28, "plastic_film": 28, "mixed_plastic": 28, "mixed_waste": 21, "biowaste": 7}
FULL_PCT = 95  # the dataset's "FULL" state ≈ fill at or above this


def build_raw(lift_at, before: dict, window: list[dict], last_lift_at, compactor: dict) -> dict:
    """
    lift_at:       time of the emptying reading
    before:        the last plausible reading before the drop {"ts", "weight_kg", "fill_pct"}
    window:        readings of the last 72 h before the lift, oldest first
    last_lift_at:  time of the previous emptying (or None)
    compactor:     row from the compactors table (material, volume_m3, …)
    """
    material = MATERIAL_MAP.get(compactor.get("material"), "other")
    full_h = 0.0
    for a, b in zip(window, window[1:]):                       # hours spent full in the last 72 h
        if (a.get("fill_pct") or 0) >= FULL_PCT:
            full_h += (b["ts"] - a["ts"]).total_seconds() / 3600
    last24 = [r for r in window if r["ts"] >= lift_at - timedelta(hours=24) and r.get("fill_pct") is not None]
    fill_rate = (max(r["fill_pct"] for r in last24) - min(r["fill_pct"] for r in last24)) / 24 if len(last24) >= 2 else None
    return {
        "feed": "esp32",                                        # picks the models trained on this feed (ml.check_lift)
        "fill_before": before.get("fill_pct"),
        "mass_before_kg": before.get("weight_kg"),
        "volume_m3": compactor.get("volume_m3"),
        "prior_kg_per_fill": None,                              # learned per device after a few lifts (future work)
        "full_hours_72h": round(full_h, 1),
        "fill_rate_24h": fill_rate,
        "cycles_24h": None, "press_max_24h": None, "sensor_bad_24h": None,   # not sent by the ESP32 node yet
        "hours_since_prev": (lift_at - last_lift_at).total_seconds() / 3600 if last_lift_at else None,
        "max_days_between_collections": MAX_DAYS.get(material),
        "delay_hours": None,
        # a SETTING, not a sensor: the fill % at which SMART orders a truck (None if the compactor has no on-call setting)
        "on_call_threshold": compactor.get("on_call_threshold_pct"),
        "lift_at": lift_at,
        "at_min_frequency": False,
        "trigger": compactor.get("trigger", "ON_CALL_ORDER"),
        "policy": compactor.get("policy", "ON_CALL"),
        "material": material,
        "equipment": compactor.get("equipment", "DUO"),
    }
