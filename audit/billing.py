"""Billing accuracy per operator x region x month, counting only evidence-backed discrepancies.

B5 counts every cent of difference between an invoice line and the Baseline-1 recomputation. Most of those
differences are recomputation noise (mass basis, rounding), which inflates over/undercharge. Here a line counts
as discrepant only if a specific, explainable rule flags it (the Task-B detector), and its delta is:
  DUPLICATE_LINE           full billed amount (overcharge)
  UNMATCHED_LINE           full billed amount (overcharge)
  WRONG_SURCHARGE          billed - expected
  WEIGHT_BASIS_MISMATCH    billed - expected (the tonnage differs from the weighbridge/device basis)
  OUTDATED_TARIFF          billed - expected, only if the billed unit price equals a superseded contract price
  MISSING_LINE             -expected amount of the absent line (undercharge when the line is a fee, overcharge
                           when it is a material credit)
  UNINVOICED_COLLECTION    -expected net amount of the job, only when a later invoice period has already been issued
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from flags import attach_expected, line_delta_and_explanation

KEY = ["operator_id", "region_code", "month"]


def billing_metrics(pub: Path, b1, b1l, flags: pd.DataFrame, keep_outdated="price_match") -> pd.DataFrame:
    inv = pd.read_parquet(pub / "finance" / "invoices.parquet", columns=["invoice_id", "contract_id", "operator_id", "billing_period", "total_eur", "n_lines", "issued_at"])
    il = pd.read_parquet(pub / "finance" / "invoice_lines.parquet")
    sites = pd.read_parquet(pub / "reference" / "sites.parquet", columns=["site_id", "region_code"])
    ct = pd.read_parquet(pub / "reference" / "contracts.parquet", columns=["contract_id", "site_id"]).merge(sites, on="site_id")
    cv = pd.read_parquet(pub / "reference" / "contract_versions.parquet")
    inv = inv.merge(ct[["contract_id", "region_code"]], on="contract_id").rename(columns={"billing_period": "month"})
    il = il.merge(inv[["invoice_id", "contract_id"] + KEY], on="invoice_id")
    fl = flags[flags.entity_type == "invoice_line"].drop_duplicates("entity_id").set_index("entity_id").label_family
    il["family"] = il.invoice_line_id.map(fl)
    il = line_delta_and_explanation(attach_expected(il, b1, b1l))     # job refs resolved like the detector
    if keep_outdated == "price_match":
        # a superseded price for the same contract: any unit price that appears in an older version of the contract
        cents_cols = [c for c in cv.columns if c.endswith("_cents") or c.endswith("_cents_per_t")]
        old = {}
        for c, g in cv.sort_values("version_no").groupby("contract_id"):
            vals = set()
            for _, row in g.iloc[:-1].iterrows():
                vals |= {round(float(row[k]) / 100, 2) for k in cents_cols if pd.notna(row[k])}
            old[c] = vals
        is_old = [round(p, 2) in old.get(c, set()) for c, p in zip(il.contract_id, il.unit_price_eur)]
        il.loc[(il.family == "OUTDATED_TARIFF") & ~np.array(is_old), "delta"] = 0.0
    elif keep_outdated == "drop":
        il.loc[il.family == "OUTDATED_TARIFF", "delta"] = 0.0
    il["discrepant"] = il.delta.abs() > 0.005

    # absent lines / uninvoiced jobs
    cf = flags[flags.entity_type == "collection"]
    b1i = b1.drop_duplicates("collection_id").set_index("collection_id")
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet", columns=["collection_id", "operator_id", "site_id", "operator_job_ref"]).merge(sites, on="site_id")
    ce = ce.set_index("collection_id")
    billed = set(zip(il.operator_job_ref, il.line_type))
    miss = []
    for cid in cf[cf.label_family == "MISSING_LINE"].entity_id:
        ref = ce.loc[cid, "operator_job_ref"]
        rows = b1l[(b1l.operator_job_ref == ref)]
        for lt, amt in rows.groupby("line_type").amount_eur.sum().items():
            if (ref, lt) not in billed and lt in ("MATERIAL_CREDIT", "LIFT_FEE", "TRANSPORT"):
                miss.append((cid, -amt))
    job_total = b1l.groupby("operator_job_ref").amount_eur.sum()
    for cid in cf[cf.label_family == "UNINVOICED_COLLECTION"].entity_id:
        miss.append((cid, -float(job_total.get(ce.loc[cid, "operator_job_ref"], 0.0))))
    m = pd.DataFrame(miss, columns=["collection_id", "delta"])
    if len(m):
        m = m.join(ce[["operator_id", "region_code"]], on="collection_id")
        m["month"] = pd.to_datetime(b1i.loc[m.collection_id, "service_date"].values).strftime("%Y-%m")

    gi = inv.groupby(KEY)
    billed_eur = gi.total_eur.sum()
    lines = il.groupby(KEY)
    d_all = lines.delta.sum()
    over = lines.delta.apply(lambda s: s[s > 0.005].sum())
    under = lines.delta.apply(lambda s: -s[s < -0.005].sum())
    n_disc = lines.discrepant.sum()
    if len(m):
        gm = m.groupby(KEY).delta
        over = over.add(gm.apply(lambda s: s[s > 0].sum()), fill_value=0)
        under = under.add(gm.apply(lambda s: -s[s < 0].sum()), fill_value=0)
        d_all = d_all.add(gm.sum(), fill_value=0)
        n_miss = gm.size()
    else:
        n_miss = pd.Series(dtype=float)
    expected = billed_eur - d_all.reindex(billed_eur.index).fillna(0)
    out = pd.DataFrame(index=billed_eur.index)
    out["billing_overcharge_pct"] = 100 * over.reindex(out.index).fillna(0) / expected.where(expected.abs() > 1)
    out["billing_undercharge_pct"] = 100 * under.reindex(out.index).fillna(0) / expected.where(expected.abs() > 1)
    out["discrepant_line_rate"] = (n_disc.reindex(out.index).fillna(0) + n_miss.reindex(out.index).fillna(0)) / \
        (gi.n_lines.sum() + n_miss.reindex(out.index).fillna(0))
    return out.reset_index()
