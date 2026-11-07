"""Task C2 — operator and contract actions by expected value, public data only.

Instead of fixed gap thresholds (baseline B6), every candidate action is valued with the PUBLISHED rules in
configs/assumptions.yaml -> operator_actions (ECONOMIC_MODEL.md §7), using our own public-data estimates:
  * contract-correct cost of the trailing window: Baseline-1 recomputation, as-of the case date
  * documented overbilling: refined Task-B invoice flags (flags.py) with their euro deltas (billing.py logic)
  * operator net above true mass: corrected-tare estimate per job (weight_bias.py)
  * each operator's billing over-rate: our scorecard billing estimate up to the case date
An action is proposed when its expected value is > 0 (renegotiate and tender are exclusive: the better one).
Every proposal carries its value, inputs and assumptions so a human can check and approve it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _engine import engine_root  # noqa: E402
ROOT = engine_root()
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "baselines")]
from europress_data.operator_tasks import FEE_FIELDS, _bucket, _peer_table, _peer_version, _reprice  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from weight_bias import job_errors  # noqa: E402

RECOVERABLE = ("DUPLICATE_LINE", "WRONG_SURCHARGE", "WEIGHT_BASIS_MISMATCH", "OUTDATED_TARIFF", "UNMATCHED_LINE")
TZ = "Europe/Helsinki"


def line_deltas(pub: Path, b1, b1l: pd.DataFrame, rflags: pd.DataFrame) -> pd.DataFrame:
    from flags import attach_expected, line_delta_and_explanation
    inv = pd.read_parquet(pub / "finance" / "invoices.parquet")
    il = pd.read_parquet(pub / "finance" / "invoice_lines.parquet").merge(
        inv[["invoice_id", "contract_id", "customer_id", "operator_id", "issued_at", "dispute_status", "total_eur"]], on="invoice_id")
    fl = rflags[rflags.entity_type == "invoice_line"].drop_duplicates("entity_id").set_index("entity_id").label_family
    il["family"] = il.invoice_line_id.map(fl)
    il = line_delta_and_explanation(attach_expected(il, b1, b1l))     # job refs resolved like the detector
    return il, inv


def decide(pub: Path, b1, b1l, rflags, with_evidence=False, cases: pd.DataFrame | None = None) -> pd.DataFrame:
    """No future data: every estimate is recomputed as of each case date (tickets published, invoices issued,
    lifts done and contract versions in force by then)."""
    OA = yaml.safe_load(open(ROOT / "configs" / "assumptions.yaml"))["operator_actions"]
    if cases is None:
        cases = pd.read_parquet(pub / "benchmark" / "operator_action_cases.parquet")
    dv = pd.read_parquet(pub / "reference" / "devices.parquet")
    ct = pd.read_parquet(pub / "reference" / "contracts.parquet")
    cv = pd.read_parquet(pub / "reference" / "contract_versions.parquet")
    cv["effective_from"] = pd.to_datetime(cv.effective_from)
    sites = pd.read_parquet(pub / "reference" / "sites.parquet", columns=["site_id", "region_code"])
    mat = pd.read_parquet(pub / "reference" / "material_classes.parquet").set_index("material_stream").credit_eligible
    pi = pd.read_parquet(pub / "reference" / "price_index_monthly.parquet")
    opr = pd.read_parquet(pub / "reference" / "operators.parquet")
    regions_of = {o: set(r.split(",")) for o, r in zip(opr.operator_id, opr.regions_served)}
    wb = pd.read_parquet(pub / "operations" / "weighbridge_tickets.parquet", columns=["operator_job_ref", "published_at"])
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet", columns=["collection_id", "contract_id", "operator_job_ref", "status", "actual_at", "device_estimated_collected_kg"])
    il, inv = line_deltas(pub, b1, b1l, rflags)

    meta = ct[["contract_id", "device_id", "operator_id", "material_stream", "site_id"]].merge(sites, on="site_id") \
        .merge(dv[["device_id", "container_volume_m3", "has_weight_measurement", "active_from"]], on="device_id")
    meta["bucket"] = meta.container_volume_m3.map(_bucket)
    idx = {(r.index_id, r.month): r.price_eur_per_t for r in pi.itertuples()}
    b = b1.merge(ct[["contract_id", "price_index_id"]], on="contract_id")
    types = b1l.groupby("collection_id").line_type.apply(set)
    ce_ref = ce.set_index("collection_id")
    ev_all = pd.DataFrame({"contract_id": b.contract_id, "collection_id": b.collection_id, "status": b.status,
                           "mass_basis": b.mass_basis, "operator_job_ref": b.operator_job_ref,
                           "device_kg": b.collection_id.map(ce_ref.device_estimated_collected_kg),
                           "service_date": pd.to_datetime(b.service_date), "billing_mass_kg": b.mass_kg, "grade_applied": b.grade,
                           "index_price_eur_per_t": [idx.get((i, str(d)[:7])) for i, d in zip(b.price_index_id, b.service_date)],
                           "emergency": [("EMERGENCY_SURCHARGE" in types.get(c, set())) for c in b.collection_id],
                           "side_waste": [("SIDE_WASTE_FEE" in types.get(c, set())) for c in b.collection_id],
                           "cancel_fee": [("CANCELLATION_FEE" in types.get(c, set())) for c in b.collection_id]})
    win_start = ev_all.service_date.min().normalize().replace(day=1)
    out, evid = [], []
    for as_of_ts, cs in cases.groupby("as_of_at"):
        as_of_local = as_of_ts.tz_convert(TZ).tz_localize(None)
        cv_k = cv[cv.effective_from < as_of_local].sort_values("version_no").groupby("contract_id").tail(1)
        cvx = cv_k.merge(meta, on="contract_id")
        peers = _peer_table(cvx)
        ops = sorted(cvx.operator_id.unique())
        peers_op = {op: _peer_table(cvx[cvx.operator_id == op]) for op in ops}
        ev_k = ev_all[ev_all.service_date < as_of_local].copy()
        il_k = il[il.issued_at <= as_of_ts]
        # a weighbridge mass is only known once its ticket is published: otherwise use the invoiced tonnage
        # (if invoiced by then), else the device estimate
        known_refs = set(wb[wb.published_at <= as_of_ts].operator_job_ref)
        inv_t = il_k[il_k.unit == "t"].groupby("operator_job_ref").quantity.max() * 1000
        late = (ev_k.mass_basis == "WEIGHBRIDGE") & ~ev_k.operator_job_ref.isin(known_refs)
        if late.any():
            repl = ev_k.loc[late, "operator_job_ref"].map(inv_t).astype(float).fillna(ev_k.loc[late, "device_kg"].astype(float))
            ev_k.loc[late, "billing_mass_kg"] = repl.values
        # operator billing over-rate up to the case date (our estimate)
        billed = inv[inv.issued_at <= as_of_ts].groupby("operator_id").total_eur.sum()
        dl = il_k.groupby("operator_id").delta.sum()
        over = il_k[il_k.delta > 0].groupby("operator_id").delta.sum()
        expd = billed - dl.reindex(billed.index).fillna(0)
        over_rate = (over.reindex(expd.index).fillna(0) / expd.where(expd > 0)).fillna(0).to_dict()
        ce_k = ce[ce.status.isin(["COMPLETED", "PARTIAL"]) & (ce.actual_at < as_of_ts)]
        pub_refs = set(wb[wb.published_at <= as_of_ts].operator_job_ref)
        je = job_errors(pub, as_of=as_of_ts)
        for c in cs.itertuples(index=False):
            cand = set(c.candidate_actions.split(","))
            r = cvx[cvx.contract_id == c.contract_id].iloc[0]
            own = {k: r[k] for k in cv.columns if k != "effective_from"}
            cred = bool(mat[r.material_stream])
            ev = ev_k[ev_k.contract_id == c.contract_id]
            a_from = pd.Timestamp(r.active_from) if pd.notna(r.active_from) else win_start
            days = max(30.0, (as_of_local - max(a_from, win_start)).days)
            ann, months_active = 365.0 / days, days / 30.4375
            base = _reprice(ev, own, cred) + int(round(int(own["rental_cents_per_month"]) * months_active))
            vals, notes, calc, rng_ = {}, {}, {}, {}
            n_l = len(ev); kb = ev.mass_basis.value_counts() if n_l else pd.Series(dtype=int)
            coverage = (f"{n_l} lifts in the window: {kb.get('WEIGHBRIDGE', 0)} with a shared weighbridge ticket, "
                        f"{kb.get('INVOICE_QUANTITY', 0)} invoice tonnage only, {kb.get('DEVICE_ESTIMATE', 0)} device weight only, "
                        f"{int(ev.billing_mass_kg.isna().sum()) if n_l else 0} unknown mass; device weighing "
                        f"{'installed' if bool(r.has_weight_measurement) else 'not installed'}")
            P_RANGE = {"DISPUTE_INVOICE": (0.7, 1.0), "REQUEST_WEIGHBRIDGE_DATA": (0.4, 0.8),
                       "RENEGOTIATE_CONTRACT": (0.3, 0.7), "TENDER_OR_SWITCH_OPERATOR": (0.6, 0.95)}
            # DISPUTE
            lc = il_k[(il_k.contract_id == c.contract_id) & (il_k.issued_at > as_of_ts - pd.Timedelta(days=OA["dispute_lookback_days"]))
                      & ~il_k.dispute_status.isin(["RESOLVED_CREDIT_NOTE", "OPEN"]) & il_k.family.isin(RECOVERABLE) & (il_k.delta > 0)]
            if not bool(r.has_weight_measurement):
                lc = lc[(lc.family != "WEIGHT_BASIS_MISMATCH") | lc.operator_job_ref.isin(pub_refs)]
            rec = 100 * lc.delta.sum()
            vals["DISPUTE_INVOICE"] = OA["dispute_recovery_rate"] * rec - OA["dispute_admin_cost_eur"] * 100
            rng_["DISPUTE_INVOICE"] = [q * rec - OA["dispute_admin_cost_eur"] * 100 for q in P_RANGE["DISPUTE_INVOICE"]]
            notes["DISPUTE_INVOICE"] = f"{len(lc)} flagged lines, documented overbilling {rec/100:.2f} EUR"
            calc["DISPUTE_INVOICE"] = (f"EV = recovery rate {OA['dispute_recovery_rate']} x documented overbilling {rec/100:,.2f} EUR "
                                       f"- admin cost {OA['dispute_admin_cost_eur']} EUR = {vals['DISPUTE_INVOICE']/100:,.2f} EUR "
                                       f"(lines issued in the last {OA['dispute_lookback_days']} days, not already disputed)")
            # REQUEST_WEIGHBRIDGE_DATA
            if "REQUEST_WEIGHBRIDGE_DATA" in cand:
                rate_t = int(own["haul_fee_cents_per_t"]) + int(own["processing_fee_cents_per_t"])
                jc = je[je.contract_id == c.contract_id]
                tare_over = max(0.0, float(jc.err_kg.sum())) / 1000 * rate_t
                wbm = il_k[(il_k.contract_id == c.contract_id) & (il_k.family == "WEIGHT_BASIS_MISMATCH") & (il_k.delta > 0)]
                wbm_unver = 0 if bool(r.has_weight_measurement) else 100 * wbm[~wbm.operator_job_ref.isin(pub_refs)].delta.sum()
                vals["REQUEST_WEIGHBRIDGE_DATA"] = OA["request_weighbridge_comply_prob"] * (tare_over + wbm_unver) * ann - OA["request_admin_cost_eur"] * 100
                rng_["REQUEST_WEIGHBRIDGE_DATA"] = [q * (tare_over + wbm_unver) * ann - OA["request_admin_cost_eur"] * 100 for q in P_RANGE["REQUEST_WEIGHBRIDGE_DATA"]]
                notes["REQUEST_WEIGHBRIDGE_DATA"] = f"est. operator net above true mass x per-t rate {tare_over/100:.2f} EUR, unverifiable tonnage claims {wbm_unver/100:.2f} EUR"
                calc["REQUEST_WEIGHBRIDGE_DATA"] = (f"EV = chance operator complies {OA['request_weighbridge_comply_prob']} x (weight over-charge {tare_over/100:,.2f} "
                                                    f"+ unverifiable tonnage claims {wbm_unver/100:,.2f}) EUR x annualisation {ann:.2f} "
                                                    f"- admin cost {OA['request_admin_cost_eur']} EUR = {vals['REQUEST_WEIGHBRIDGE_DATA']/100:,.2f} EUR")
            rowd = pd.Series(dict(region_code=r.region_code, material_stream=r.material_stream, pricing_model=own["pricing_model"], bucket=r.bucket))
            if "RENEGOTIATE_CONTRACT" in cand:
                p, lv = _peer_version(rowd, peers)
                if p is not None:
                    nv = dict(own)
                    for f in FEE_FIELDS:
                        nv[f] = int(round(p[f]))
                    nv["credit_share_bp"] = int(round(p["credit_share_bp"] / 100) * 100) if cred else 0
                    rc = _reprice(ev, nv, cred) + int(round(int(nv["rental_cents_per_month"]) * months_active))
                    gap = base - rc
                    ok = base > 0 and gap >= OA["renegotiation_min_gap_pct"] / 100 * base
                    vals["RENEGOTIATE_CONTRACT"] = (OA["renegotiation_success_prob"] * gap * ann if ok else 0.0) - OA["renegotiation_effort_eur"] * 100
                    rng_["RENEGOTIATE_CONTRACT"] = [(q * gap * ann if ok else 0.0) - OA["renegotiation_effort_eur"] * 100 for q in P_RANGE["RENEGOTIATE_CONTRACT"]]
                    notes["RENEGOTIATE_CONTRACT"] = f"peer level {lv}, annual gap {gap*ann/100:.0f} EUR ({100*gap/max(base,1):.1f} %)"
                    calc["RENEGOTIATE_CONTRACT"] = (
                        f"EV = acceptance chance {OA['renegotiation_success_prob']} x annual gap to peer-median terms {gap*ann/100:,.0f} EUR "
                        f"- effort {OA['renegotiation_effort_eur']} EUR = {vals['RENEGOTIATE_CONTRACT']/100:,.2f} EUR" if ok else
                        f"Gap to peer terms is {100*gap/max(base,1):.1f} %, below the {OA['renegotiation_min_gap_pct']} % the operator considers, "
                        f"so EV = - effort {OA['renegotiation_effort_eur']} EUR")
            if "TENDER_OR_SWITCH_OPERATOR" in cand:
                mb = max(0.0, OA["valuation_horizon_months"] - int(c.notice_period_days) / 30.4375)
                best = None
                for op in ops:
                    if op == c.operator_id or r.region_code not in regions_of.get(op, set()):
                        continue
                    pv, _ = _peer_version(rowd, peers_op[op], min_n=2)
                    if pv is None:
                        continue
                    av = dict(own)
                    for f in FEE_FIELDS + ["free_km"]:
                        av[f] = int(round(pv[f]))
                    av["credit_share_bp"] = int(round(pv["credit_share_bp"] / 100) * 100) if cred else 0
                    alt = _reprice(ev, av, cred) + int(round(int(av["rental_cents_per_month"]) * months_active))
                    cur_t = base * (1 + over_rate.get(c.operator_id, 0.0))
                    alt_t = alt * (1 + over_rate.get(op, 0.0))
                    g = cur_t - alt_t
                    ok = cur_t > 0 and g >= OA["tender_min_gap_pct"] / 100 * cur_t
                    v = (OA["tender_success_prob"] * g * ann * mb / 12 if ok else 0.0) - OA["tender_switch_cost_eur"] * 100
                    if best is None or v > best[0]:
                        best = (v, op, g * ann / 100, ok, 100 * g / max(cur_t, 1), mb)
                if best:
                    vals["TENDER_OR_SWITCH_OPERATOR"] = best[0]
                    gain = (best[0] + OA["tender_switch_cost_eur"] * 100) / OA["tender_success_prob"] if best[3] else 0.0
                    rng_["TENDER_OR_SWITCH_OPERATOR"] = [q * gain - OA["tender_switch_cost_eur"] * 100 for q in P_RANGE["TENDER_OR_SWITCH_OPERATOR"]]
                    notes["TENDER_OR_SWITCH_OPERATOR"] = f"best alternative {best[1]}, annual difference incl. billing accuracy {best[2]:.0f} EUR"
                    calc["TENDER_OR_SWITCH_OPERATOR"] = (
                        f"EV = tender success chance {OA['tender_success_prob']} x annual difference {best[2]:,.0f} EUR x {best[5]:.1f}/12 "
                        f"(months left in the {OA['valuation_horizon_months']}-month horizon after the {int(c.notice_period_days)}-day notice) "
                        f"- tendering and switching cost {OA['tender_switch_cost_eur']} EUR = {best[0]/100:,.2f} EUR" if best[3] else
                        f"Best alternative is only {best[4]:.1f} % cheaper, below the {OA['tender_min_gap_pct']} % needed, "
                        f"so EV = - switching cost {OA['tender_switch_cost_eur']} EUR")
            vals = {a: v for a, v in vals.items() if a in cand}
            chosen = [a for a in ("DISPUTE_INVOICE", "REQUEST_WEIGHBRIDGE_DATA") if vals.get(a, -1) > 0]
            ex = [(vals[a], a) for a in ("RENEGOTIATE_CONTRACT", "TENDER_OR_SWITCH_OPERATOR") if vals.get(a, -1) > 0]
            if ex:
                chosen.append(max(ex)[1])
            out.append({"case_id": c.case_id, "actions": ";".join(chosen)})
            for a, v in vals.items():
                evid.append({"case_id": c.case_id, "contract_id": c.contract_id, "action": a, "expected_value_eur": round(v / 100, 2),
                             "proposed": a in chosen, "evidence": notes.get(a, ""), "calculation": calc.get(a, ""),
                             "ev_low_eur": round(min(rng_.get(a, [v, v])) / 100, 2), "ev_high_eur": round(max(rng_.get(a, [v, v])) / 100, 2),
                             "uncertainty": (f"EV range uses a success/recovery probability of {P_RANGE[a][0]}-{P_RANGE[a][1]} around the published "
                                             f"value (team assumption). Data coverage: {coverage}."),
                             "evidence_tag": "inputs estimated from customer documents and device data; valuation rules hypothetical",
                             "status": "PROPOSAL - needs human approval"})
    res = pd.DataFrame(out)
    return (res, pd.DataFrame(evid)) if with_evidence else res


def decide_causal(pub: Path, cache: Path, log=print):
    """C2 from as-of snapshots: for each case date, the public package is cut at that date (the data pack's own
    as-of rules) and EVERY input is recomputed from the snapshot: Baseline-1 economics, invoice flags and deltas,
    tare estimates, peers, operator billing rates. Dispute status is hidden as of the date (UNKNOWN_AS_OF)."""
    from b1_economic_calculator import compute
    from b2_rules_anomaly import detect_invoices
    from flags import refine_flags
    from snapshot import make_snapshot
    cases = pd.read_parquet(pub / "benchmark" / "operator_action_cases.parquet")
    res, evid = [], []
    for as_of_ts, cs in cases.groupby("as_of_at"):
        day = as_of_ts.tz_convert(TZ).normalize()          # snapshot at local midnight on/before the case time
        snap = make_snapshot(pub, day.strftime("%Y-%m-%d"), cache)
        b1, b1l = compute(snap)
        rf = refine_flags(snap, b1, detect_invoices(snap, b1, b1l), b1l)
        r, e = decide(snap, b1, b1l, rf, with_evidence=True, cases=cs)
        res.append(r); evid.append(e.assign(snapshot_date=day.strftime("%Y-%m-%d")))
        log(f"  C2 cases at {as_of_ts}: snapshot {day:%Y-%m-%d}, {len(cs)} cases")
    return pd.concat(res, ignore_index=True), pd.concat(evid, ignore_index=True)
