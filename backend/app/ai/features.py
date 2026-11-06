"""Features for ML models. Owner: AI person.

SHARED by the backend (live) and training/train_anomaly.py (offline), so a model
always sees the same numbers it was trained on. Change it -> retrain the models.

Values are scaled to the compactor's size, so one model works for all compactors.
"""
FEATURES = ["weight_frac", "delta_frac", "fill_frac", "density_ratio"]


def make_features(weight_kg, fill_pct, prev_weight_kg, compactor: dict, material: dict) -> dict:
    cap = compactor["capacity_kg"]
    density = 0.0
    if fill_pct and fill_pct >= 20 and weight_kg > 0:
        density = weight_kg / (fill_pct / 100 * compactor["volume_m3"])
    return {
        "weight_frac": weight_kg / cap,
        "delta_frac": (weight_kg - prev_weight_kg) / cap if prev_weight_kg is not None else 0.0,
        "fill_frac": (fill_pct or 0) / 100,
        "density_ratio": density / material["density_max"],
    }
