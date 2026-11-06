"""Build the Customer Value Cockpit from the official Europress synthetic dataset. Owner: data person.

    python analytics/build_cockpit.py                       # local Docker Postgres
    python analytics/build_cockpit.py --db "<TigerData URL>"

Reads the dataset with the organisers' own calculators (baselines B1, B2, B5, B6 from the engine package),
adds plain-language evidence and a euro impact to every finding, and writes cp_* tables that Grafana and the
backend show. Every figure carries an evidence tag: OBSERVED (customer/operator record), ESTIMATED (device or
our calculation), HYPOTHETICAL (contract tariff, synthetic). All data is synthetic.

Engine location: --engine or env EUROPRESS_ENGINE (default ./europress/Europress_SMART_Material_Value_Engine_v1.0.1)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENGINE = ROOT / "europress" / "Europress_SMART_Material_Value_Engine_v1.0.1"

FAMILY_TEXT = {
    "PREMATURE_UNJUSTIFIED": "Lift with a low fill level and no hygiene/contract reason: possibly an unnecessary lift",
    "COST_PER_T_HIGH": "Collection cost per tonne is more than 2x the benchmark for this material",
    "DELAYED_COLLECTION": "Container was full for many hours before the lift: overflow / side-waste risk",
    "WEIGHT_DISCREPANCY": "Device weight and operator weighbridge differ by more than 10 %",
    "CONTAMINATION_VALUE_LOSS": "Low quality grade (C/R) reduced or removed the material credit",
    "REJECTED_LOAD": "Load was rejected at the facility",
    "OUTDATED_TARIFF": "Invoice line uses a price that differs from the contract version in force",
    "DUPLICATE_LINE": "The same charge appears twice on the invoice",
    "WRONG_SURCHARGE": "Surcharge does not match the contract terms",
    "WEIGHT_BASIS_MISMATCH": "Invoiced tonnage differs from the weighbridge record",
    "UNMATCHED_LINE": "Invoice line has no matching collection",
    "MISSING_LINE": "A contracted charge or credit is missing from the invoice",
    "UNINVOICED_COLLECTION": "Completed collection never appeared on an invoice",
}
ACTION_TEXT = {
    "DISPUTE_INVOICE": "Recent invoice lines differ from the contract calculation: ask the operator to review them",
    "REQUEST_WEIGHBRIDGE_DATA": "Per-tonne pricing without shared weighbridge data or device weight: ask the operator to share tickets",
    "RENEGOTIATE_CONTRACT": "Contract terms are clearly above similar contracts (peer median): prepare a renegotiation",
    "TENDER_OR_SWITCH_OPERATOR": "Terms far above peers: consider tendering the service (respect the notice period)",
}
MASS_EVIDENCE = {"WEIGHBRIDGE": "OBSERVED", "INVOICE_QUANTITY": "OBSERVED", "DEVICE_ESTIMATE": "ESTIMATED"}


def load_engine(engine_dir: Path):
    sys.path.insert(0, str(engine_dir / "src"))
    sys.path.insert(0, str(engine_dir / "baselines"))
    from b1_economic_calculator import compute
    from b2_rules_anomaly import collection_features, detect_collections, detect_invoices
    from b5_operator_scorecard import scorecard
    from b6_operator_actions import decide as decide_c2
    return compute, collection_features, detect_collections, detect_invoices, scorecard, decide_c2


def build(pub: Path, engine_dir: Path) -> dict[str, pd.DataFrame]:
    compute, collection_features, detect_collections, detect_invoices, scorecard, decide_c2 = load_engine(engine_dir)
    t0 = time.time()
    b1, b1l = compute(pub)
    feats = collection_features(pub, b1)
    coll_flags = detect_collections(feats)
    inv_flags = detect_invoices(pub, b1, b1l)
    sc = scorecard(pub, b1, b1l)
    c2 = decide_c2(pub, b1, b1l, inv_flags)
    print(f"engine calculators done in {time.time() - t0:.0f}s", flush=True)

    rd = lambda t: pd.read_parquet(pub / f"{t}.parquet")  # noqa: E731
    ce, dev, sites, cust, ops = (rd("operations/collection_events"), rd("reference/devices"),
                                 rd("reference/sites"), rd("reference/customers"), rd("reference/operators"))
    wb = rd("operations/weighbridge_tickets")
    il = rd("finance/invoice_lines")

    # ---------- collections: economics per lift ----------
    col = (b1.merge(ce[["collection_id", "site_id", "customer_id", "operator_id", "trigger_type", "actual_at",
                        "device_fill_pct_before", "device_estimated_collected_kg"]], on="collection_id", how="left")
             .merge(dev[["device_id", "material_stream", "equipment_class", "collection_policy"]], on="device_id", how="left")
             .merge(sites[["site_id", "site_name", "region_code"]], on="site_id", how="left")
             .merge(cust[["customer_id", "customer_name"]], on="customer_id", how="left")
             .merge(ops[["operator_id", "operator_name"]], on="operator_id", how="left"))
    tickets = wb.groupby("operator_job_ref", as_index=False).allocated_net_kg.sum().rename(columns={"allocated_net_kg": "weighbridge_net_kg"})
    col = col.merge(tickets, on="operator_job_ref", how="left")
    col["mass_evidence"] = col.mass_basis.map(MASS_EVIDENCE).fillna("NONE")
    col["service_date"] = pd.to_datetime(col.service_date, utc=True)

    # ---------- findings with evidence and euro at stake ----------
    cf = coll_flags.merge(col, left_on="entity_id", right_on="collection_id", how="left")
    excess = ((cf.collection_cost_eur_per_t - cf.benchmark_eur_per_t) * cf.mass_kg / 1000).clip(lower=0)
    cf["eur_at_stake"] = 0.0
    cf.loc[cf.label_family == "PREMATURE_UNJUSTIFIED", "eur_at_stake"] = cf.collection_cost_eur
    cf.loc[cf.label_family == "COST_PER_T_HIGH", "eur_at_stake"] = excess
    cf.loc[cf.label_family.isin(["CONTAMINATION_VALUE_LOSS", "REJECTED_LOAD"]), "eur_at_stake"] = cf.penalties_eur
    cf["evidence"] = cf.apply(lambda r: (
        f"fill before lift {r.device_fill_pct_before:.0f} %" if pd.notna(r.device_fill_pct_before) else "fill unknown")
        + (f"; device {r.device_estimated_collected_kg:.0f} kg" if pd.notna(r.device_estimated_collected_kg) else "")
        + (f"; weighbridge {r.weighbridge_net_kg:.0f} kg" if pd.notna(r.weighbridge_net_kg) else "; no shared ticket")
        + (f"; {r.collection_cost_eur_per_t:.0f} EUR/t vs benchmark {r.benchmark_eur_per_t:.0f}" if pd.notna(r.collection_cost_eur_per_t) else ""),
        axis=1)
    cf = cf.assign(entity_type="collection", found_at=cf.service_date)[
        ["entity_type", "entity_id", "label_family", "found_at", "device_id", "customer_name", "site_name",
         "operator_name", "material_stream", "eur_at_stake", "evidence"]]

    ilf = inv_flags.merge(il[["invoice_line_id", "invoice_id", "line_type", "service_date", "operator_job_ref", "amount_eur"]],
                          left_on="entity_id", right_on="invoice_line_id", how="left")
    ilf = ilf.merge(col[["operator_job_ref", "device_id", "customer_name", "site_name", "operator_name", "material_stream"]]
                    .drop_duplicates("operator_job_ref"), on="operator_job_ref", how="left")
    ilf["eur_at_stake"] = ilf.amount_eur.abs().fillna(0)
    ilf["evidence"] = ilf.apply(lambda r: f"invoice {r.invoice_id}, line {r.line_type}, {r.amount_eur:.2f} EUR", axis=1)
    ilf = ilf.assign(entity_type="invoice_line", found_at=pd.to_datetime(ilf.service_date, utc=True))[
        ["entity_type", "entity_id", "label_family", "found_at", "device_id", "customer_name", "site_name",
         "operator_name", "material_stream", "eur_at_stake", "evidence"]]

    flags = pd.concat([cf, ilf], ignore_index=True)
    flags["explanation"] = flags.label_family.map(FAMILY_TEXT)
    flags["evidence_tag"] = "ESTIMATED"  # our rule on observed records -> a finding to check, not a fact
    flags["eur_at_stake"] = flags.eur_at_stake.round(2)

    # ---------- operator scorecard ----------
    sc = sc.merge(ops[["operator_id", "operator_name"]], on="operator_id", how="left")

    # ---------- recommended actions (need human approval) ----------
    cases = rd("benchmark/operator_action_cases")
    split = lambda v: [x for x in (v.split(";") if isinstance(v, str) else list(v or [])) if x]  # noqa: E731
    acts = c2.assign(actions=c2.actions.map(split)).explode("actions").dropna(subset=["actions"]).rename(columns={"actions": "action"})
    acts = acts.merge(cases[["case_id", "contract_id", "device_id", "customer_id", "operator_id", "notice_period_days"]], on="case_id", how="left")
    acts = (acts.merge(cust[["customer_id", "customer_name"]], on="customer_id", how="left")
                .merge(ops[["operator_id", "operator_name"]], on="operator_id", how="left"))
    stake = flags[flags.entity_type == "invoice_line"].groupby("device_id").eur_at_stake.sum()
    acts["flagged_invoice_eur"] = acts.device_id.map(stake).fillna(0).round(2)
    acts["rationale"] = acts.action.map(ACTION_TEXT)
    acts["action_id"] = acts.case_id + "-" + acts.action
    acts = acts[["action_id", "case_id", "action", "contract_id", "device_id", "customer_name", "operator_name",
                 "notice_period_days", "flagged_invoice_eur", "rationale"]]

    keep = ["collection_id", "device_id", "contract_id", "operator_job_ref", "status", "service_date", "customer_name",
            "site_name", "region_code", "operator_name", "material_stream", "equipment_class", "collection_policy",
            "trigger_type", "device_fill_pct_before", "device_estimated_collected_kg", "weighbridge_net_kg", "mass_kg",
            "mass_basis", "mass_evidence", "collection_cost_eur", "processing_cost_eur", "penalties_eur",
            "material_credit_eur", "net_material_contribution_eur", "collection_cost_eur_per_t", "benchmark_eur_per_t"]
    return {"cp_collections": col[keep], "cp_flags": flags, "cp_scorecard": sc, "cp_actions": acts}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", default=os.getenv("EUROPRESS_ENGINE", str(DEFAULT_ENGINE)))
    p.add_argument("--profile", default="competition", choices=["competition", "quickstart"])
    p.add_argument("--db", default=os.getenv("DATABASE_URL", "postgresql+psycopg://compactor:compactor@localhost:5432/compactor"))
    a = p.parse_args()
    engine_dir = Path(a.engine)
    pub = engine_dir / "data" / a.profile / "public"
    if not pub.exists():
        raise SystemExit(f"Dataset not found at {pub}. Unzip the Europress package into ./europress/ (see analytics/README.md)")
    tables = build(pub, engine_dir)
    url = a.db.replace("postgres://", "postgresql+psycopg://", 1) if a.db.startswith("postgres://") else a.db
    db = create_engine(url)
    with db.begin() as conn:
        for name, df in tables.items():
            df.to_sql(name, conn, if_exists="replace", index=False, chunksize=max(1, 60000 // max(1, len(df.columns))), method="multi")
            print(f"{name}: {len(df)} rows")
        if db.dialect.name == "postgresql":
            conn.execute(text("CREATE INDEX IF NOT EXISTS cp_flags_family ON cp_flags (label_family)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS cp_coll_date ON cp_collections (service_date)"))
    print("Cockpit ready. Open Grafana -> 'Customer Value Cockpit'.")


if __name__ == "__main__":
    main()
