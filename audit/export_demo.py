"""Export tidy, customer-keyed tables for the demo dashboard (every figure tagged by evidence type)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FAMILY_TEXT = {
    "PREMATURE_UNJUSTIFIED": "Lift with a low fill/mass: likely unnecessary (check hygiene/max-interval rules first)",
    "DELAYED_COLLECTION": "Lift later than needed: overflow / side-waste risk",
    "WEIGHT_DISCREPANCY": "Device weight and operator weighbridge disagree",
    "COST_PER_T_HIGH": "Cost per tonne well above comparable contracts",
    "CONTAMINATION_VALUE_LOSS": "Material credit lost to contamination (operator grade)",
    "MOISTURE_HEAVY_LOAD": "Unusually heavy load for its volume (moisture?)",
    "REJECTED_LOAD": "Load rejected at the facility",
    "MISSING_LINE": "Expected invoice line absent",
    "UNINVOICED_COLLECTION": "Completed lift never invoiced",
    "DUPLICATE_LINE": "Invoice line billed twice",
    "OUTDATED_TARIFF": "Unit price from a superseded contract version",
    "WRONG_SURCHARGE": "Surcharge does not match the contract",
    "WEIGHT_BASIS_MISMATCH": "Invoiced tonnage differs from the weighbridge/device basis",
    "UNMATCHED_LINE": "Invoice line matches no recorded lift",
}


def export(pub: Path, out: Path, b1, b1l, flags: pd.DataFrame, job_err: pd.DataFrame, line_delta: pd.DataFrame):
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet")
    dv = pd.read_parquet(pub / "reference" / "devices.parquet", columns=["device_id", "material_stream", "equipment_class", "has_weight_measurement"])
    cu = pd.read_parquet(pub / "reference" / "customers.parquet")
    name_col = next((c for c in cu.columns if "name" in c), None)
    cu = cu[["customer_id"] + ([name_col] if name_col else [])].rename(columns={name_col: "customer_name"} if name_col else {})
    sites = pd.read_parquet(pub / "reference" / "sites.parquet", columns=["site_id", "region_code"])

    col = ce[["collection_id", "customer_id", "site_id", "device_id", "operator_id", "status", "trigger_type", "actual_at",
              "device_fill_pct_before", "device_estimated_collected_kg"]] \
        .merge(b1[["collection_id", "mass_kg", "mass_basis", "collection_cost_eur", "net_material_contribution_eur",
                   "collection_cost_eur_per_t", "benchmark_eur_per_t"]], on="collection_id", how="left") \
        .merge(dv, on="device_id", how="left").merge(sites, on="site_id", how="left") \
        .merge(job_err[["collection_id", "allocated_net_kg", "true_net_est_kg", "err_kg", "evidence"]], on="collection_id", how="left")
    col = col.rename(columns={"evidence": "weight_evidence"})
    col.to_csv(out / "demo_collections.csv", index=False)

    # findings keyed by customer
    f = flags.copy()
    c_map = ce.set_index("collection_id")[["customer_id", "device_id", "actual_at"]]
    il = line_delta.set_index("invoice_line_id")
    rows = []
    for r in f.itertuples(index=False):
        d = dict(entity_type=r.entity_type, entity_id=r.entity_id, family=r.label_family,
                 what=FAMILY_TEXT.get(r.label_family, r.label_family), customer_id=None, device_id=None, when=None,
                 eur_delta=np.nan, evidence_type="estimated")
        if r.entity_type == "collection" and r.entity_id in c_map.index:
            x = c_map.loc[r.entity_id]
            d.update(customer_id=x.customer_id, device_id=x.device_id, when=x.actual_at)
        elif r.entity_type == "invoice_line" and r.entity_id in il.index:
            x = il.loc[r.entity_id]
            d.update(customer_id=x.customer_id, when=x.issued_at, eur_delta=round(float(x.delta), 2),
                     evidence_type="observed (invoice) vs estimated (contract recomputation)",
                     detail=f"{x.line_type} {x.operator_job_ref}: billed {x.amount_eur:.2f} EUR, contract-recomputed {x.exp:.2f} EUR",
                     calculation=x.calculation)
        rows.append(d)
    fd = pd.DataFrame(rows).dropna(subset=["customer_id"])
    # neutral cause attribution for weight differences + evidence tags
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parent))
    from causes import attribute
    cz = attribute(pub)
    cz.to_parquet(out / "trail_causes.parquet", index=False)
    cmap = cz.set_index("collection_id")
    fd["side"] = fd.entity_id.map(cmap.side)
    fd["likely_cause"] = fd.entity_id.map(cmap.cause_text)
    inv_note = line_delta.set_index("invoice_line_id").ref_note if "ref_note" in line_delta else pd.Series(dtype=str)
    typo = fd.entity_type.eq("invoice_line") & fd.entity_id.map(inv_note).fillna("").str.startswith("reference")
    fd.loc[typo, "side"] = "DATA_ENTRY"
    fd.loc[typo, "likely_cause"] = "Invoice line carries a mistyped job reference (resolved to the matching lift)"
    fd.loc[fd.entity_type.eq("invoice_line") & fd.side.isna(), "side"] = "BILLING"
    fd["evidence_tag"] = np.where(fd.entity_type.eq("invoice_line"),
                                  "observed (billed line) vs estimated (contract recomputation)",
                                  "estimated (device data and rules; operator data observed where shared)")
    fd.to_csv(out / "demo_findings.csv", index=False)
    cu.to_csv(out / "demo_customers.csv", index=False)
    # row-level audit trail: lift -> ticket -> contract version -> expected lines -> billed lines
    from weight_bias import ticket_truth_estimate
    t, _veh = ticket_truth_estimate(pub)
    tcols = [c for c in ["operator_job_ref", "ticket_id", "weighing_event_id", "vehicle_id", "gross_kg", "tare_kg", "tare_method", "net_kg",
                         "loads_on_vehicle", "allocated_net_kg", "real_tare_kg", "true_net_est_kg", "published_at"] if c in t.columns]
    t[tcols].to_parquet(out / "trail_tickets.parquet", index=False)
    b1l.merge(b1[["collection_id", "contract_id", "contract_version_id", "mass_kg", "mass_basis", "grade", "service_date"]],
              on="collection_id", how="left").to_parquet(out / "trail_expected_lines.parquet", index=False)
    lcols = [c for c in ["invoice_line_id", "invoice_id", "issued_at", "dispute_status", "contract_id", "customer_id", "operator_job_ref",
                         "resolved_ref", "ref_note", "service_date", "line_type", "quantity", "unit_price_eur", "amount_eur", "exp",
                         "family", "delta", "calculation"] if c in line_delta.columns]
    line_delta[lcols].to_parquet(out / "trail_invoice_lines.parquet", index=False)
    pd.read_parquet(pub / "reference" / "contract_versions.parquet").to_parquet(out / "trail_contract_versions.parquet", index=False)
    # reference loads for the weighing-accuracy SENSITIVITY simulation: only clean tickets (single load AND a weighed,
    # not stored, vehicle tare), because stored tares carry the bias that weight_bias.py corrects
    wb = pd.read_parquet(pub / "operations" / "weighbridge_tickets.parquet")
    one = wb[(wb.loads_on_vehicle == 1) & (wb.allocated_net_kg > 100) & (wb.tare_method == "WEIGHED")][["operator_job_ref", "allocated_net_kg"]]
    d = ce[ce.status == "COMPLETED"].merge(one, on="operator_job_ref")
    d = d[~d.driver_reported_side_waste.fillna(False).astype(bool)]
    d[["allocated_net_kg"]].rename(columns={"allocated_net_kg": "reference_kg"}).to_csv(out / "demo_reference_loads.csv", index=False)
    cases = pd.read_parquet(pub / "benchmark" / "operator_action_cases.parquet", columns=["case_id", "customer_id", "operator_id", "device_id"])
    cases.to_csv(out / "demo_c2_cases.csv", index=False)
