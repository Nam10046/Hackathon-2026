"""Features for the LIVE LIFT MODEL. Owner: AI person.

SHARED by training (training/train_lift_model.py, on the Europress dataset) and the live backend
(when a real compactor is emptied). Only information a compactor has AT THE MOMENT OF THE LIFT is used:
its own sensor history (fill, weight, press load, cycles, status), its settings and the clock.
No weighbridge tickets, invoices or prices — so the same model works on live ESP32 / SMART data.

Change anything here -> retrain the model.
"""
import math

TRIGGERS = ["ON_CALL_ORDER", "SCHEDULED", "MAX_INTERVAL_RULE", "CUSTOMER_REQUEST", "AD_HOC_CUSTOMER",
            "CUSTOMER_REQUEST_PRE_CLOSURE", "OTHER"]
POLICIES = ["ON_CALL", "FIXED_SCHEDULE", "HYBRID", "OTHER"]
MATERIALS = ["cardboard", "mixed_waste", "plastic_film", "biowaste", "paper", "mixed_plastic", "other"]
EQUIPMENT = ["DUO", "COMBI", "OTHER"]

NUMERIC = [
    "fill_before", "mass_before_kg", "density_kg_m3", "kg_per_fill_ratio",
    "full_hours_72h", "fill_rate_24h", "cycles_24h", "press_max_24h", "sensor_bad_24h",
    "hours_since_prev", "hygiene_pressure", "delay_hours", "on_call_threshold",
    "hour", "is_friday", "is_weekend", "at_min_frequency",
]
FEATURES = (NUMERIC + [f"trigger_{t}" for t in TRIGGERS] + [f"policy_{p}" for p in POLICIES]
            + [f"material_{m}" for m in MATERIALS] + [f"equipment_{e}" for e in EQUIPMENT])


def _num(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _onehot(prefix, value, vocab):
    value = value if value in vocab else vocab[-1]
    return {f"{prefix}_{v}": 1.0 if v == value else 0.0 for v in vocab}


def encode(raw: dict) -> dict:
    """raw -> {feature: float}. Missing values become NaN (the model handles them).

    raw keys: fill_before, mass_before_kg, volume_m3, prior_kg_per_fill (device's usual kg per fill %),
    full_hours_72h, fill_rate_24h, cycles_24h, press_max_24h, sensor_bad_24h, hours_since_prev,
    max_days_between_collections, delay_hours, on_call_threshold, lift_at (datetime), at_min_frequency,
    trigger, policy, material, equipment
    """
    fill, mass, vol = _num(raw.get("fill_before")), _num(raw.get("mass_before_kg")), _num(raw.get("volume_m3"))
    density = mass / (fill / 100 * vol) if fill >= 10 and vol > 0 and mass > 0 else float("nan")
    kpf = mass / fill if fill >= 10 and mass > 0 else float("nan")
    prior = _num(raw.get("prior_kg_per_fill"))
    max_days = _num(raw.get("max_days_between_collections"))
    at = raw.get("lift_at")
    out = {
        "fill_before": fill,
        "mass_before_kg": mass,
        "density_kg_m3": density,
        # < 1 = less weight than usual for this fill level -> fill sensor may read falsely high
        "kg_per_fill_ratio": kpf / prior if prior > 0 and kpf == kpf else float("nan"),
        "full_hours_72h": _num(raw.get("full_hours_72h")),
        "fill_rate_24h": _num(raw.get("fill_rate_24h")),
        "cycles_24h": _num(raw.get("cycles_24h")),
        "press_max_24h": _num(raw.get("press_max_24h")),
        "sensor_bad_24h": _num(raw.get("sensor_bad_24h")),
        "hours_since_prev": _num(raw.get("hours_since_prev")),
        # >= 1 = hygiene / contract maximum days reached -> an early lift is justified
        "hygiene_pressure": _num(raw.get("hours_since_prev")) / (max_days * 24) if max_days > 0 else float("nan"),
        "delay_hours": _num(raw.get("delay_hours")),
        "on_call_threshold": _num(raw.get("on_call_threshold")),
        "hour": float(at.hour) if at is not None else float("nan"),
        "is_friday": float(at.weekday() == 4) if at is not None else float("nan"),
        "is_weekend": float(at.weekday() >= 5) if at is not None else float("nan"),
        "at_min_frequency": float(bool(raw.get("at_min_frequency"))),
    }
    out.update(_onehot("trigger", raw.get("trigger"), TRIGGERS))
    out.update(_onehot("policy", raw.get("policy"), POLICIES))
    out.update(_onehot("material", raw.get("material"), MATERIALS))
    out.update(_onehot("equipment", raw.get("equipment"), EQUIPMENT))
    return out


MISSING = -1.0  # "unknown" for the model (all real feature values are >= 0)


def to_vector(raw: dict) -> list[float]:
    f = encode(raw)
    return [MISSING if f[k] != f[k] else f[k] for k in FEATURES]  # NaN -> MISSING
