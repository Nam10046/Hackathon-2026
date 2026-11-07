"""Neutral cause attribution for device-vs-weighbridge weight differences (public data only, fixed rules).

For every completed lift with both a device mass and a shared ticket, the difference is attributed to ONE side:
  LOGISTICS  SIDE_WASTE_ON_SAME_TRUCK   driver reported side waste: extra material, not an error
  LOGISTICS  COMBINED_LOAD_ALLOCATION   the truck carried several loads and the operator split the net equally
  OPERATOR   WEIGHBRIDGE_TARE_ERROR     the ticket used a STORED truck tare that differs from that truck's weighed tares,
                                        and correcting it moves the ticket towards the device
  DEVICE     DEVICE_SENSOR              the device disagrees with the tare-corrected ticket beyond its accuracy, and the
                                        device's own recent lifts show the same bias, or a weight recalibration /
                                        sensor replacement follows within 30 days
  NOISE      MEASUREMENT_NOISE          difference within max(60 kg, 4 %) of the load
  UNKNOWN    UNEXPLAINED                none of the above
Order matters: logistics first (no one is at fault), then the operator's data, then the device. The rules are fixed
in code; train-period labels are used only to REPORT how often the attribution agrees with the simulator's cause.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SIDE = {"SIDE_WASTE_ON_SAME_TRUCK": "LOGISTICS", "COMBINED_LOAD_ALLOCATION": "LOGISTICS", "WEIGHBRIDGE_TARE_ERROR": "OPERATOR",
        "DEVICE_SENSOR": "DEVICE", "MEASUREMENT_NOISE": "NOISE", "UNEXPLAINED": "UNKNOWN"}
TEXT = {"SIDE_WASTE_ON_SAME_TRUCK": "Driver reported side waste: extra material on the truck, not an error by anyone",
        "COMBINED_LOAD_ALLOCATION": "Several loads on one truck; the operator split the net weight equally",
        "WEIGHBRIDGE_TARE_ERROR": "Ticket used a stale stored truck tare; correcting it brings the ticket close to the device",
        "DEVICE_SENSOR": "Device reading off beyond its accuracy (drift or recalibration): a device issue, not the operator",
        "MEASUREMENT_NOISE": "Within normal measurement tolerance",
        "UNEXPLAINED": "No observable cause; review with the operator neutrally"}


def attribute(pub: Path) -> pd.DataFrame:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from weight_bias import ticket_truth_estimate
    t, veh = ticket_truth_estimate(pub)
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet")
    wo = pd.read_parquet(pub / "operations" / "maintenance_work_orders.parquet")
    d = ce[ce.status == "COMPLETED"].merge(
        t[["operator_job_ref", "tare_method", "loads_on_vehicle", "allocated_net_kg", "true_net_est_kg", "vehicle_id"]]
        .rename(columns={"vehicle_id": "ticket_vehicle"}), on="operator_job_ref", how="inner")
    d = d[d.device_estimated_collected_kg.notna() & (d.allocated_net_kg > 0)].copy()
    d["diff_ticket_kg"] = d.device_estimated_collected_kg - d.allocated_net_kg
    d["diff_corrected_kg"] = d.device_estimated_collected_kg - d.true_net_est_kg
    tol = np.maximum(60, 0.04 * d.allocated_net_kg)
    terr = d.ticket_vehicle.map(veh.tare_error_kg).fillna(0)
    # device bias: rolling median of device / corrected ticket over the device's previous 5 single-load lifts
    d = d.sort_values(["device_id", "actual_at"])
    ratio = (d.device_estimated_collected_kg / d.true_net_est_kg).where(d.loads_on_vehicle == 1)
    d["device_bias"] = ratio.groupby(d.device_id).transform(lambda s: s.shift(1).rolling(5, min_periods=3).median()) - 1
    fix = wo[wo.work_order_type.isin(["SENSOR_RECALIBRATION", "SENSOR_REPLACEMENT"])][["device_id", "reported_at"]]
    nxt = d[["collection_id", "device_id", "actual_at"]].merge(fix, on="device_id", how="left")
    nxt = nxt[(nxt.reported_at >= nxt.actual_at) & (nxt.reported_at <= nxt.actual_at + pd.Timedelta(days=30))]
    soon_fix = set(nxt.collection_id)
    cause = np.select(
        [d.driver_reported_side_waste.fillna(False).astype(bool),
         d.loads_on_vehicle > 1,
         (d.diff_ticket_kg.abs() <= tol),
         (d.tare_method == "STORED") & (terr.abs() >= 50) & (d.diff_corrected_kg.abs() < d.diff_ticket_kg.abs()) & (d.diff_corrected_kg.abs() <= tol),
         (d.diff_corrected_kg.abs() > tol) & ((d.device_bias.abs() > 0.03) | d.collection_id.isin(soon_fix))],
        ["SIDE_WASTE_ON_SAME_TRUCK", "COMBINED_LOAD_ALLOCATION", "MEASUREMENT_NOISE", "WEIGHBRIDGE_TARE_ERROR", "DEVICE_SENSOR"],
        default="UNEXPLAINED")
    d["cause"] = cause
    d["side"] = d.cause.map(SIDE)
    d["cause_text"] = d.cause.map(TEXT)
    d["actionable"] = d.side.isin(["OPERATOR", "DEVICE"])
    return d[["collection_id", "device_id", "operator_id", "actual_at", "device_estimated_collected_kg", "allocated_net_kg",
              "true_net_est_kg", "tare_method", "loads_on_vehicle", "diff_ticket_kg", "diff_corrected_kg", "device_bias",
              "cause", "side", "cause_text", "actionable"]]
