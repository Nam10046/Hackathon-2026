"""Operator weight bias from public data, correcting the two known weighbridge error sources.

Idea (traceable, rule-based):
  1. A vehicle's real tare is stable: estimate it as the median of its WEIGHED tares on shared tickets.
  2. Tickets with a STORED tare carry the error (stored - real tare); the true net is gross - real tare.
  3. Combined loads (2 jobs on one truck) are split equally by the operator; we re-split the corrected net
     in proportion to the two devices' own mass estimates when both are available.
  4. Unshared tickets: expected error = P(stored tare | vehicle) x (real tare - stored tare); the mass basis is
     the invoice tonnage, else the device estimate.
Every quantity is observed (ticket fields) or estimated (tare, split, unshared error) and labelled as such.

No future data: every function takes `as_of` and uses only tickets PUBLISHED and invoices ISSUED by then, and
only lifts that happened before it. Task C2 calls it at each case date; the B2 scorecard calls it once per
month, as of the date that month's report can be issued (month end + 15 days, when its invoices are out).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TZ = "Europe/Helsinki"
KEY = ["operator_id", "region_code", "month"]


def ticket_truth_estimate(pub: Path, as_of=None) -> pd.DataFrame:
    wb = pd.read_parquet(pub / "operations" / "weighbridge_tickets.parquet")
    if as_of is not None:
        wb = wb[wb.published_at <= as_of]
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet",
                         columns=["collection_id", "operator_job_ref", "device_estimated_collected_kg"])
    weighed = wb[wb.tare_method == "WEIGHED"].groupby("vehicle_id").tare_kg.median().rename("real_tare_kg")
    stored = wb[wb.tare_method == "STORED"].groupby("vehicle_id").tare_kg.median().rename("stored_tare_kg")
    p_stored = (wb.tare_method == "STORED").groupby(wb.vehicle_id).mean().rename("p_stored")
    veh = pd.concat([weighed, stored, p_stored], axis=1)
    veh["tare_error_kg"] = (veh.stored_tare_kg - veh.real_tare_kg).fillna(0.0)     # >0: net understated

    t = wb.merge(veh[["real_tare_kg"]], left_on="vehicle_id", right_index=True, how="left")
    corr_net = np.where((t.tare_method == "STORED") & t.real_tare_kg.notna(), t.gross_kg - t.real_tare_kg, t.net_kg)
    t["event_true_net_est_kg"] = corr_net
    t = t.merge(ce[["operator_job_ref", "device_estimated_collected_kg"]], on="operator_job_ref", how="left")
    # re-split combined loads by device estimates
    dev = t.device_estimated_collected_kg.where(t.device_estimated_collected_kg > 50)
    g = t.groupby("weighing_event_id")
    dev_sum = dev.groupby(t.weighing_event_id).transform("sum")
    dev_cnt = dev.groupby(t.weighing_event_id).transform("count")
    share = np.where((t.loads_on_vehicle > 1) & (dev_cnt == t.loads_on_vehicle), dev / dev_sum, 1.0 / t.loads_on_vehicle)
    t["true_net_est_kg"] = t.event_true_net_est_kg * share
    t["true_net_est_kg"] = t.true_net_est_kg.clip(lower=0)
    return t, veh


def job_errors(pub: Path, as_of=None) -> pd.DataFrame:
    """Per completed job before `as_of`: estimated operator net minus true mass (kg) and the mass basis."""
    t, veh = ticket_truth_estimate(pub, as_of)
    t = t.drop_duplicates("operator_job_ref")
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet")
    sites = pd.read_parquet(pub / "reference" / "sites.parquet", columns=["site_id", "region_code"])
    ce = ce.merge(sites, on="site_id")
    comp = ce[ce.status.isin(["COMPLETED", "PARTIAL"])].copy()
    if as_of is not None:
        comp = comp[comp.actual_at < as_of]
    comp["month"] = comp.scheduled_at.dt.tz_convert(TZ).dt.strftime("%Y-%m")
    # invoice tonnage per job (WEIGHT-type lines carry t), from invoices issued by `as_of`
    il = pd.read_parquet(pub / "finance" / "invoice_lines.parquet", columns=["invoice_id", "operator_job_ref", "unit", "quantity"])
    if as_of is not None:
        iss = pd.read_parquet(pub / "finance" / "invoices.parquet", columns=["invoice_id", "issued_at"])
        il = il[il.invoice_id.isin(iss[iss.issued_at <= as_of].invoice_id)]
    inv_t = il[il.unit == "t"].groupby("operator_job_ref").quantity.max().rename("invoice_t")
    w = comp.merge(t[["operator_job_ref", "allocated_net_kg", "true_net_est_kg"]], on="operator_job_ref", how="left")
    w = w.merge(inv_t, left_on="operator_job_ref", right_index=True, how="left")
    w = w.merge(veh[["p_stored", "tare_error_kg"]], left_on="vehicle_id", right_index=True, how="left")
    shared = w.allocated_net_kg.notna()
    # shared tickets: observed allocated - estimated true
    w["err_kg"] = np.where(shared, w.allocated_net_kg - w.true_net_est_kg, np.nan)
    w["mass_kg"] = np.where(shared, w.true_net_est_kg, np.nan)
    # unshared: expected error from the vehicle's stored-tare habit
    mass_u = (w.invoice_t * 1000).where(w.invoice_t.notna(), w.device_estimated_collected_kg)
    exp_err = -(w.p_stored.fillna(0) * w.tare_error_kg.fillna(0))
    w.loc[~shared, "err_kg"] = exp_err[~shared]
    w.loc[~shared, "mass_kg"] = mass_u[~shared]
    # evidence class per job: a shared ticket = MEASURED; unshared but the truck's tare habit is known from its
    # other shared tickets = MODEL_ESTIMATE; neither = NONE (no evidence: the error is unknown, NOT zero)
    veh_known = w.vehicle_id.isin(veh.index[veh.real_tare_kg.notna()])
    w["evidence_class"] = np.where(shared, "MEASURED", np.where(veh_known, "MODEL_ESTIMATE", "NONE"))
    w.loc[w.evidence_class == "NONE", "err_kg"] = np.nan
    w = w.dropna(subset=["mass_kg"])
    w = w[w.mass_kg > 0]
    w["evidence"] = w.evidence_class.map({"MEASURED": "shared ticket, tare-corrected true mass (estimated)",
                                          "MODEL_ESTIMATE": "unshared: expected error from the vehicle's stored-tare habit (estimated)",
                                          "NONE": "no ticket and no tare evidence for this truck: unverifiable"})
    return w


FINAL_REPORT_LAG_DAYS = 45     # operators share tickets at most 45 days late (docs/ASSUMPTIONS_AND_LIMITATIONS.md)
PRELIM_REPORT_LAG_DAYS = 15    # a month's invoices are issued by the 15th of the next month


def report_date(month: str, lag_days: int = FINAL_REPORT_LAG_DAYS) -> pd.Timestamp:
    """Data cut-off of a month's scorecard: the end of the `lag_days`-th full day after the month ends.

    Month end = 24:00 on the last day (= 00:00 on the 1st of the next month, Europe/Helsinki). The cut-off is that
    instant + lag_days x 24 h, and the snapshot keeps data stamped strictly BEFORE it. Example for January 2026:
      preliminary (15): cut 2026-02-16 00:00 local -> includes everything issued on or before 15 Feb
      final (45):       cut 2026-03-18 00:00 local -> a lift at 31 Jan 23:59 with the maximum 45-day ticket lag
                        (published 17 Mar 23:59) is included, nothing later is.
    This is the same rule the data pack uses to decide which months are dev months (month end + 15 days).
    Days are CALENDAR days in Europe/Helsinki: the date is computed on the naive local calendar first and only then
    localised, so a daylight-saving change inside the window does not shift the cut-off by an hour or a day."""
    first_next = pd.Timestamp(month + "-01") + pd.offsets.MonthBegin(1)
    local_cutoff = (first_next + pd.Timedelta(days=lag_days)).tz_localize(TZ)
    return local_cutoff.tz_convert("UTC")


def aggregate_bias(w: pd.DataFrame) -> pd.DataFrame:
    """Per operator x region x month: bias over jobs WITH evidence, the mass share by evidence class and a status.
    UNVERIFIABLE rows get weight_bias_pct = NaN here; fill_prior() adds a labelled prior for scoring."""
    rows = []
    for k, g in w.groupby(KEY):
        ev = g[g.evidence_class != "NONE"]
        m = g.mass_kg.sum()
        meas = g.loc[g.evidence_class == "MEASURED", "mass_kg"].sum() / m if m else 0.0
        anyev = ev.mass_kg.sum() / m if m else 0.0
        bias = 100 * ev.err_kg.sum() / ev.mass_kg.sum() if ev.mass_kg.sum() > 0 else np.nan
        status = "MEASURED" if meas >= 0.5 else ("MODEL_ESTIMATE" if anyev > 0 else "UNVERIFIABLE")
        rows.append((*k, bias, status, round(meas, 4), round(anyev, 4)))
    return pd.DataFrame(rows, columns=KEY + ["weight_bias_pct", "weight_bias_status", "weight_evidence_measured_share",
                                            "weight_evidence_any_share"])


def fill_prior(df: pd.DataFrame) -> pd.DataFrame:
    """UNVERIFIABLE rows: weight_bias_pct = median of the verifiable rows (a labelled PRIOR, not a measurement)."""
    df = df.copy()
    prior = df.loc[df.weight_bias_status != "UNVERIFIABLE", "weight_bias_pct"].median()
    df["weight_bias_prior_used"] = df.weight_bias_status == "UNVERIFIABLE"
    df.loc[df.weight_bias_prior_used, "weight_bias_pct"] = prior
    return df


def weight_bias(pub: Path, causal: bool = True) -> pd.DataFrame:
    """Operator weight bias per operator x region x month. causal=True: each month only sees data
    published by its report date (no future data)."""
    if not causal:
        return fill_prior(aggregate_bias(job_errors(pub)))
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet", columns=["scheduled_at"])
    months = sorted(ce.scheduled_at.dt.tz_convert(TZ).dt.strftime("%Y-%m").unique())
    parts = []
    for m in months:
        w = job_errors(pub, as_of=report_date(m))
        w = w[w.month == m]
        if len(w):
            parts.append(fill_prior(aggregate_bias(w)))      # prior from the same month's snapshot only
    return pd.concat(parts, ignore_index=True)
