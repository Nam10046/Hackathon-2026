"""Build the Customer Value Cockpit from the official Europress synthetic dataset. Owner: data person.

    python analytics/build_cockpit.py                       # local Docker Postgres
    python analytics/build_cockpit.py --db "<TigerData URL>"

Problems (Task B), waste-company scorecard (Task B2) and proposed actions (Task C2) come from the team's audit
pipeline in ./audit (run `python audit/run_solution.py competition` first: it writes audit/outputs/<profile>/),
with our live lift model for early/late lifts. If those outputs are missing, the organisers' baselines
(B2 rules, B5, B6) are used instead and the cockpit says so. Lift costs always come from the organisers' B1 calculator.
Adds plain-language evidence and a euro impact to every finding, and writes cp_* tables that Grafana and the
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
AUDIT_OUT = ROOT / "audit" / "outputs"          # written by audit/run_solution.py

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
    from europress_data.sdk import open_dataset
    return compute, collection_features, detect_collections, detect_invoices, scorecard, decide_c2, open_dataset


LIFT_MODELS = {"lift_premature": "PREMATURE_UNJUSTIFIED", "lift_delayed": "DELAYED_COLLECTION"}


def model_flags(pub, b1, compute, collection_features, open_dataset) -> pd.DataFrame | None:
    """Our live lift model (models/lift_*) instead of the simple rules for early / late lifts. None if not available."""
    try:
        import json
        import onnxruntime as ort
        sys.path.insert(0, str(ROOT / "training"))
        from lift_dataset import build_raw, to_matrix
    except ImportError as e:
        print(f"lift model not used ({e}); using the organisers' rules for early/late lifts")
        return None
    folders = [ROOT / "models" / m for m in LIFT_MODELS if (ROOT / "models" / m / "model.onnx").exists()]
    if not folders:
        return None
    f = build_raw(pub, compute, collection_features, open_dataset, b1=b1)
    X = to_matrix(f)
    out = []
    for folder in folders:
        meta = json.loads((folder / "model.json").read_text())
        sess = ort.InferenceSession(str(folder / "model.onnx"))
        prob = sess.run(None, {sess.get_inputs()[0].name: X})[1][:, 1]
        hit = f.collection_id.to_numpy()[prob >= meta["threshold"]]
        out.append(pd.DataFrame({"entity_type": "collection", "entity_id": hit, "label_family": meta["family"]}))
        print(f"{folder.name}: {len(hit)} lifts flagged by the model")
    return pd.concat(out, ignore_index=True)


def build(pub: Path, engine_dir: Path, audit_dir: Path | None = None, profile: str = "competition") -> dict[str, pd.DataFrame]:
    compute, collection_features, detect_collections, detect_invoices, scorecard, decide_c2, open_dataset = load_engine(engine_dir)
    t0 = time.time()
    b1, b1l = compute(pub)
    mf = model_flags(pub, b1, compute, collection_features, open_dataset)
    audit = None
    if audit_dir is not None and (audit_dir / "demo_findings.csv").exists():
        audit = {n: pd.read_csv(audit_dir / f"{n}.csv") for n in
                 ["demo_findings", "b2_operator_scorecard", "c2_action_evidence", "b_family_selection"]}
        print(f"using the team audit outputs in {audit_dir}", flush=True)
        coll_flags = (mf.assign(detected_by="our live lift model") if mf is not None
                      else pd.DataFrame(columns=["entity_type", "entity_id", "label_family", "detected_by"]))
        inv_flags = pd.DataFrame(columns=["entity_type", "entity_id", "label_family", "detected_by"])
        sc = c2 = None
    else:
        print("team audit outputs not found -> organisers' baselines B2/B5/B6 (run audit/run_solution.py for the better ones)", flush=True)
        feats = collection_features(pub, b1)
        coll_flags = detect_collections(feats).assign(detected_by="rules (organisers' B2)")
        if mf is not None:                   # model replaces the rules for the families it covers
            coll_flags = pd.concat([coll_flags[~coll_flags.label_family.isin(mf.label_family.unique())],
                                    mf.assign(detected_by="our live lift model")], ignore_index=True)
        inv_flags = detect_invoices(pub, b1, b1l).assign(detected_by="rules (organisers' B2)")
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
         "operator_name", "material_stream", "eur_at_stake", "evidence", "detected_by"]]

    ilf = inv_flags.merge(il[["invoice_line_id", "invoice_id", "line_type", "service_date", "operator_job_ref", "amount_eur"]],
                          left_on="entity_id", right_on="invoice_line_id", how="left")
    ilf = ilf.merge(col[["operator_job_ref", "device_id", "customer_name", "site_name", "operator_name", "material_stream"]]
                    .drop_duplicates("operator_job_ref"), on="operator_job_ref", how="left")
    ilf["eur_at_stake"] = ilf.amount_eur.abs().fillna(0)
    ilf["evidence"] = ilf.apply(lambda r: f"invoice {r.invoice_id}, line {r.line_type}, {r.amount_eur:.2f} EUR", axis=1)
    ilf = ilf.assign(entity_type="invoice_line", found_at=pd.to_datetime(ilf.service_date, utc=True))[
        ["entity_type", "entity_id", "label_family", "found_at", "device_id", "customer_name", "site_name",
         "operator_name", "material_stream", "eur_at_stake", "evidence", "detected_by"]]

    flags = pd.concat([cf, ilf], ignore_index=True)
    flags["explanation"] = flags.label_family.map(FAMILY_TEXT)
    flags["evidence_tag"] = "estimated (device data and rules)"   # a finding to check, not a fact
    flags["calculation"] = None
    flags["likely_cause"] = None
    flags["side"] = None

    if audit is not None:
        fnd = audit["demo_findings"].rename(columns={"family": "label_family"})
        chosen = dict(zip(audit["b_family_selection"].family, audit["b_family_selection"].chosen))
        # our lift model covers its families; keep the audit's cause explanation for those lifts
        cause = fnd.set_index(["entity_id", "label_family"])[["likely_cause", "side"]]
        if len(flags):
            ix = pd.MultiIndex.from_arrays([flags.entity_id, flags.label_family])
            flags["likely_cause"] = cause.likely_cause.reindex(ix).to_numpy()
            flags["side"] = cause.side.reindex(ix).to_numpy()
        fnd = fnd[~fnd.label_family.isin(flags.label_family.unique())]
        # same lookups as our own rows: collection -> its lift; invoice line -> the device's site/operator
        byc = col.set_index("collection_id")
        is_col = fnd.entity_type.eq("collection")
        # invoice lines carry no device: invoice -> contract -> that contract's lifts (site, material, device)
        inv = rd("finance/invoices").merge(ops[["operator_id", "operator_name"]], on="operator_id", how="left")
        line_inv = fnd.entity_id.map(il.set_index("invoice_line_id").invoice_id).map(inv.set_index("invoice_id").contract_id)
        byk = col.drop_duplicates("contract_id").set_index("contract_id")
        fnd["device_id"] = fnd.device_id.fillna(line_inv.map(byk.device_id))
        line_op = fnd.entity_id.map(il.set_index("invoice_line_id").invoice_id).map(inv.set_index("invoice_id").operator_name)
        look = lambda c: fnd.entity_id.map(byc[c]).where(is_col, line_op if c == "operator_name" else line_inv.map(byk[c]))  # noqa: E731
        excess = ((byc.collection_cost_eur_per_t - byc.benchmark_eur_per_t) * byc.mass_kg / 1000).clip(lower=0)
        coll_eur = pd.Series(0.0, index=fnd.index)
        coll_eur[fnd.label_family.eq("COST_PER_T_HIGH")] = fnd.entity_id.map(excess)
        coll_eur[fnd.label_family.isin(["CONTAMINATION_VALUE_LOSS", "REJECTED_LOAD"])] = fnd.entity_id.map(byc.penalties_eur)
        af = pd.DataFrame({
            "entity_type": fnd.entity_type, "entity_id": fnd.entity_id, "label_family": fnd.label_family,
            "found_at": pd.to_datetime(fnd["when"], utc=True), "device_id": fnd.device_id,
            "customer_name": fnd.customer_id.map(cust.set_index("customer_id").customer_name),
            "site_name": look("site_name"), "operator_name": look("operator_name"), "material_stream": look("material_stream"),
            # invoice lines: the audit's evidence-based difference (typo-safe job matching); lifts: our euro rule
            "eur_at_stake": fnd.eur_delta.abs().where(fnd.eur_delta.notna(), coll_eur.fillna(0)),
            "evidence": fnd.detail.fillna(""), "detected_by": fnd.label_family.map(
                lambda f: f"team audit ({'ML' if chosen.get(f) == 'ML' else 'rules'})"),
            "explanation": fnd.what, "evidence_tag": fnd.evidence_tag, "calculation": fnd.calculation,
            "likely_cause": fnd.likely_cause, "side": fnd.side})
        flags = pd.concat([flags, af], ignore_index=True)
    flags["eur_at_stake"] = flags.eur_at_stake.astype(float).round(2)

    # ---------- issues: the same problem on the same compactor counted once ----------
    key = flags.device_id.fillna("customer:" + flags.customer_name.fillna("unknown"))
    issues = (flags.assign(issue_key=key).groupby(["issue_key", "label_family"], as_index=False)
              .agg(device_id=("device_id", "first"), customer_name=("customer_name", "first"), site_name=("site_name", "first"),
                   operator_name=("operator_name", "first"), material_stream=("material_stream", "first"),
                   times_seen=("entity_id", "count"), first_seen=("found_at", "min"), last_seen=("found_at", "max"),
                   eur_at_stake=("eur_at_stake", "sum"), example_record=("entity_id", "first"), detected_by=("detected_by", "first"),
                   likely_cause=("likely_cause", lambda v: v.dropna().mode().iat[0] if v.notna().any() else None),
                   side=("side", lambda v: v.dropna().mode().iat[0] if v.notna().any() else None)))
    issues["eur_at_stake"] = issues.eur_at_stake.round(2)
    issues["explanation"] = issues.label_family.map(FAMILY_TEXT)

    # ---------- operator scorecard ----------
    if audit is not None:
        sc = audit["b2_operator_scorecard"]            # final report: month end + 45 days, as-of snapshots
    sc = sc.merge(ops[["operator_id", "operator_name"]], on="operator_id", how="left")

    # ---------- recommended actions (need human approval) ----------
    cases = rd("benchmark/operator_action_cases")
    if audit is not None:
        ev = audit["c2_action_evidence"]
        acts = ev[ev.proposed.astype(str).str.lower().eq("true")].copy()   # decided as of the case date (no future data)
        acts["action_key"] = profile + ":" + acts.case_id + ":" + acts.action
        acts = acts.drop(columns=["contract_id"])
    else:
        split = lambda v: [x for x in (v.split(";") if isinstance(v, str) else list(v or [])) if x]  # noqa: E731
        acts = c2.assign(actions=c2.actions.map(split)).explode("actions").dropna(subset=["actions"]).rename(columns={"actions": "action"})
        acts["action_key"] = profile + ":" + acts.case_id + ":" + acts.action
        for c in ["expected_value_eur", "ev_low_eur", "ev_high_eur", "evidence", "calculation", "uncertainty", "snapshot_date"]:
            acts[c] = None
        acts["evidence_tag"] = "organisers' B6 rules (may use data published after the decision date)"
    acts = acts.merge(cases[["case_id", "contract_id", "device_id", "customer_id", "operator_id", "notice_period_days"]], on="case_id", how="left")
    acts = (acts.merge(cust[["customer_id", "customer_name"]], on="customer_id", how="left")
                .merge(ops[["operator_id", "operator_name"]], on="operator_id", how="left"))
    stake = flags[flags.entity_type == "invoice_line"].groupby("device_id").eur_at_stake.sum()
    acts["flagged_invoice_eur"] = acts.device_id.map(stake).fillna(0).round(2)
    acts["rationale"] = acts.action.map(ACTION_TEXT)
    # decision key = (dataset, case, action): a decision can never attach to another dataset's proposal
    acts["action_id"] = acts.action_key
    acts = acts[["action_id", "case_id", "action", "contract_id", "device_id", "customer_name", "operator_name",
                 "notice_period_days", "flagged_invoice_eur", "rationale", "expected_value_eur", "ev_low_eur",
                 "ev_high_eur", "evidence", "calculation", "uncertainty", "evidence_tag", "snapshot_date"]]

    keep = ["collection_id", "device_id", "contract_id", "operator_job_ref", "status", "service_date", "customer_name",
            "site_name", "region_code", "operator_name", "material_stream", "equipment_class", "collection_policy",
            "trigger_type", "device_fill_pct_before", "device_estimated_collected_kg", "weighbridge_net_kg", "mass_kg",
            "mass_basis", "mass_evidence", "collection_cost_eur", "processing_cost_eur", "penalties_eur",
            "material_credit_eur", "net_material_contribution_eur", "collection_cost_eur_per_t", "benchmark_eur_per_t"]
    return {"cp_collections": col[keep], "cp_flags": flags, "cp_issues": issues, "cp_scorecard": sc, "cp_actions": acts}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", default=os.getenv("EUROPRESS_ENGINE", str(DEFAULT_ENGINE)))
    p.add_argument("--profile", default="competition", choices=["competition", "quickstart"])
    p.add_argument("--audit", default=None, help="team audit outputs (default audit/outputs/<profile>)")
    p.add_argument("--db", default=os.getenv("DATABASE_URL", "postgresql+psycopg://compactor:compactor@localhost:5432/compactor"))
    a = p.parse_args()
    engine_dir = Path(a.engine)
    pub = engine_dir / "data" / a.profile / "public"
    if not pub.exists():
        raise SystemExit(f"Dataset not found at {pub}. Unzip the Europress package into ./europress/ (see analytics/README.md)")
    audit_dir = Path(a.audit) if a.audit else AUDIT_OUT / a.profile
    tables = build(pub, engine_dir, audit_dir, a.profile)
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
