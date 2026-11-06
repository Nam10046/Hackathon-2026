"""Lift features for the Europress dataset — shared by training/train_lift_model.py and analytics/build_cockpit.py.
No scikit-learn needed here (the cockpit only scores the ONNX model)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.lift_features import to_vector  # noqa: E402


def build_raw(pub: Path, compute, collection_features, open_dataset, b1=None) -> pd.DataFrame:
    """One row per completed lift with every live-known input (see lift_features.py)."""
    if b1 is None:
        b1, _ = compute(pub)
    f = collection_features(pub, b1)            # organisers' features; we keep only the live-known ones
    f = f[f.status.isin(["COMPLETED", "PARTIAL"])].copy()
    con = open_dataset(pub)
    tele = con.sql("""
        SELECT c.collection_id,
               max(t.fill_pct) - min(t.fill_pct)                                   AS fill_range_24h,
               sum(t.compaction_cycles)                                            AS cycles_24h,
               max(t.press_load_index)                                             AS press_max_24h,
               sum(CASE WHEN t.sensor_status IN ('DEGRADED','FAULT') THEN 1 ELSE 0 END) AS sensor_bad_24h
        FROM collection_events c
        JOIN telemetry_dedup t ON t.device_id = c.device_id
         AND t.measured_at < c.actual_at AND t.measured_at >= c.actual_at - INTERVAL 24 HOUR
        WHERE c.status IN ('COMPLETED','PARTIAL') GROUP BY 1""").df()
    dev = con.sql("SELECT device_id, equipment_class, on_call_threshold_pct FROM devices").df()
    con.close()
    f = f.merge(tele, on="collection_id", how="left").merge(dev, on="device_id", how="left")
    f["fill_rate_24h"] = f.fill_range_24h / 24
    # the device's usual kg per fill-% from its EARLIER lifts only (no peeking into the future)
    f = f.sort_values(["device_id", "actual_at"])
    kpf = (f.device_mass_kg_before / f.device_fill_pct_before.where(f.device_fill_pct_before >= 10)).where(f.device_mass_kg_before > 0)
    f["prior_kg_per_fill"] = kpf.groupby(f.device_id).transform(lambda s: s.expanding().median().shift(1))
    return f


def to_matrix(f: pd.DataFrame) -> np.ndarray:
    rows = []
    for r in f.itertuples(index=False):
        rows.append(to_vector({
            "fill_before": r.device_fill_pct_before, "mass_before_kg": r.device_mass_kg_before,
            "volume_m3": r.container_volume_m3, "prior_kg_per_fill": r.prior_kg_per_fill,
            "full_hours_72h": r.full_hours_72h, "fill_rate_24h": r.fill_rate_24h, "cycles_24h": r.cycles_24h,
            "press_max_24h": r.press_max_24h, "sensor_bad_24h": r.sensor_bad_24h,
            "hours_since_prev": r.hours_since_prev, "max_days_between_collections": r.max_days_between_collections,
            "delay_hours": r.delay_hours, "on_call_threshold": r.on_call_threshold_pct,
            "lift_at": r.actual_at, "at_min_frequency": r.at_min_frequency,
            "trigger": r.original_trigger_type, "policy": r.collection_policy,
            "material": r.material_stream, "equipment": r.equipment_class,
        }))
    return np.array(rows, dtype=np.float32)
