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


# What each feed knows. "full" = the dataset's SMART device + order system. "esp32" = only weight, fill and clock
# (exactly what backend/app/ai/live_lift.py can fill in today). "esp32_order" = esp32 + the lift's order type.
FEEDS = ["full", "esp32", "esp32_order"]
LIVE_UNKNOWN = ["prior_kg_per_fill", "cycles_24h", "press_max_24h", "sensor_bad_24h", "delay_hours", "on_call_threshold"]
LIVE_DEFAULTS = {"trigger": "ON_CALL_ORDER", "policy": "ON_CALL", "equipment": "DUO", "at_min_frequency": False}


def raw_rows(f: pd.DataFrame) -> list[dict]:
    return [{"fill_before": r.device_fill_pct_before, "mass_before_kg": r.device_mass_kg_before,
             "volume_m3": r.container_volume_m3, "prior_kg_per_fill": r.prior_kg_per_fill,
             "full_hours_72h": r.full_hours_72h, "fill_rate_24h": r.fill_rate_24h, "cycles_24h": r.cycles_24h,
             "press_max_24h": r.press_max_24h, "sensor_bad_24h": r.sensor_bad_24h,
             "hours_since_prev": r.hours_since_prev, "max_days_between_collections": r.max_days_between_collections,
             "delay_hours": r.delay_hours, "on_call_threshold": r.on_call_threshold_pct, "lift_at": r.actual_at,
             "at_min_frequency": r.at_min_frequency, "trigger": r.original_trigger_type,
             "policy": r.collection_policy, "material": r.material_stream, "equipment": r.equipment_class}
            for r in f.itertuples(index=False)]


def limit_to_feed(raw: dict, feed: str) -> dict:
    """Hide what a given live feed does not know (same defaults the backend uses)."""
    raw = dict(raw)
    if feed in ("esp32", "esp32_order"):
        for k in LIVE_UNKNOWN:
            raw[k] = None
        raw["at_min_frequency"] = LIVE_DEFAULTS["at_min_frequency"]
        raw["equipment"] = LIVE_DEFAULTS["equipment"]
        if feed == "esp32":
            raw["trigger"], raw["policy"] = LIVE_DEFAULTS["trigger"], LIVE_DEFAULTS["policy"]
    return raw


def to_matrix(f: pd.DataFrame, feed: str = "full") -> np.ndarray:
    return np.array([to_vector(limit_to_feed(r, feed)) for r in raw_rows(f)], dtype=np.float32)


def live_matrix(pub: Path, f: pd.DataFrame, open_dataset) -> np.ndarray:
    """ESP32 feed computed EXACTLY like the live backend: backend/app/ai/live_lift.build_raw on the raw hourly
    readings (weight, fill, time) — no organiser features. Training on this removes train/serve skew."""
    from datetime import timedelta
    from app.ai.live_lift import build_raw as live_build_raw
    con = open_dataset(pub)
    tele = con.sql("SELECT device_id, measured_at, mass_kg, fill_pct FROM telemetry_dedup "
                   "WHERE mass_kg IS NOT NULL ORDER BY device_id, measured_at").df()
    dev = con.sql("SELECT device_id, material_stream, container_volume_m3 FROM devices").df().set_index("device_id")
    con.close()
    tele["measured_at"] = pd.to_datetime(tele.measured_at, utc=True)
    tele["fill_pct"] = tele.fill_pct.clip(0, 100)
    rows = {}
    for device_id, lf in f.assign(actual_at=pd.to_datetime(f.actual_at, utc=True)).sort_values("actual_at").groupby("device_id"):
        t = tele[tele.device_id == device_id]
        ts, w = t.measured_at.dt.tz_convert(None).to_numpy("datetime64[ns]"), t.mass_kg.to_numpy(dtype=float)
        fill = t.fill_pct.to_numpy(dtype=float)
        cap = float(np.nanpercentile(w, 99)) if len(w) else 1.0            # stands in for the registered capacity
        comp = {"material": dev.material_stream.get(device_id), "volume_m3": dev.container_volume_m3.get(device_id)}
        prev_lift = None
        for r in lf.itertuples():
            i = int(np.searchsorted(ts, r.actual_at.tz_convert(None).to_datetime64(), side="left"))
            lift_at = pd.Timestamp(ts[i], tz="UTC").to_pydatetime() if i < len(ts) else r.actual_at.to_pydatetime()
            j0 = int(np.searchsorted(ts, (pd.Timestamp(lift_at).tz_convert(None) - timedelta(hours=72)).to_datetime64(), side="left"))
            ok = [k for k in range(j0, i) if -20 <= w[k] <= cap * 1.3]
            if not ok:
                rows[r.collection_id] = None
                prev_lift = lift_at
                continue
            window = [{"ts": pd.Timestamp(ts[k], tz="UTC").to_pydatetime(), "weight_kg": w[k],
                       "fill_pct": None if np.isnan(fill[k]) else fill[k]} for k in range(j0, i)]
            b = ok[-1]
            before = {"ts": window[b - j0]["ts"], "weight_kg": w[b], "fill_pct": window[b - j0]["fill_pct"]}
            rows[r.collection_id] = to_vector(live_build_raw(lift_at, before, window, prev_lift, comp))
            prev_lift = lift_at
    from app.ai.lift_features import MISSING
    empty = [MISSING] * len(next(v for v in rows.values() if v is not None))
    return np.array([rows.get(c) or empty for c in f.collection_id], dtype=np.float32)
