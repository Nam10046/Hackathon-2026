"""SMART Service Audit — demo dashboard (synthetic data).

    python solution/run_solution.py competition     # creates solution/outputs/competition/
    streamlit run solution/app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import cost_per_tonne_known  # noqa: E402

HERE = Path(__file__).resolve().parent
st.set_page_config(page_title="SMART Service Audit", page_icon="⚖️", layout="wide")

profile = st.sidebar.selectbox("Dataset", ["competition", "quickstart"])
OUT = HERE / "outputs" / profile
if not (OUT / "scores.json").exists():
    st.error(f"No results for '{profile}'. Run:  python solution/run_solution.py {profile}")
    st.stop()


@st.cache_data
def load(p: str):
    o = Path(p)
    col = pd.read_csv(o / "demo_collections.csv", parse_dates=["actual_at"])
    fnd = pd.read_csv(o / "demo_findings.csv")
    cus = pd.read_csv(o / "demo_customers.csv")
    ev = pd.read_csv(o / "c2_action_evidence.csv").merge(pd.read_csv(o / "demo_c2_cases.csv"), on="case_id", how="left")
    sc = pd.read_csv(o / "b2_operator_scorecard.csv")
    ref = pd.read_csv(o / "demo_reference_loads.csv").reference_kg.to_numpy(float)
    scores = json.load(open(o / "scores.json"))
    return col, fnd, cus, ev, sc, ref, scores


col, fnd, cus, ev, sc, ref, scores = load(str(OUT))
names = dict(zip(cus.customer_id, cus.get("customer_name", cus.customer_id)))
if "decisions" not in st.session_state:
    st.session_state.decisions = {}

st.sidebar.markdown("---")
page = st.sidebar.radio("View", ["1 · Overview", "2 · Customer audit", "3 · Action inbox", "4 · Operator scorecard",
                                 "5 · Weighing accuracy", "6 · SMART integration", "7 · Lift audit trail"])
st.sidebar.caption("SYNTHETIC DATA. Fictional customers and operators. Figures show the method, not real savings. "
                   "Every recommendation is a proposal that needs human approval.")
st.sidebar.markdown("**Evidence tags**  \n"
                    "`observed` recorded by a party (ticket, invoice, device)  \n"
                    "`estimated` derived by our rules or recomputation  \n"
                    "`simulated` sensitivity model  \n"
                    "`hypothetical` an assumption (prices, probabilities, adoption)")
if "decision_events" not in st.session_state:
    st.session_state.decision_events = []

# ------------------------------------------------------------------ 1 Overview
if page.startswith("1"):
    st.title("SMART Service Audit")
    st.markdown("**An independent, explainable view of the waste services a customer buys** — built from SMART device "
                "data (fill, weight, status) and the customer's own contracts and invoices.")
    c = st.columns(3)
    b2 = scores["task_B2_score_0_100"]; c2 = scores["task_C2_dev"]; b = scores["task_B_macro_f1_validation"]
    KB2, KC2, KB = "ours: final report, month end + 45 d (primary)", "ours (as-of snapshots, primary)", "per-family ML/rules selection (ours, primary)"
    c[0].metric("Operator scorecard accuracy (B2, 0–100)", f"{b2[KB2]:.1f}", f"+{b2[KB2] - b2['B5 (baseline)']:.1f} vs baseline")
    c[1].metric("Action regret per contract (C2)", f"{c2[KC2]['mean_regret_eur']:.0f} €",
                f"{c2[KC2]['mean_regret_eur'] - c2['B6 (baseline)']['mean_regret_eur']:.0f} € vs baseline", delta_color="inverse")
    c[2].metric("Anomaly detection macro-F1 (B)", f"{b[KB]:.3f}",
                f"+{b[KB] - b['hybrid ML+rules (baseline)']:.3f} vs baseline")
    st.caption("Scored with the official harness on public dev/validation labels. Only train-period labels are used to fit "
               "or choose anything (Task B); validation labels only score. "
               "B2 and C2 use as-of snapshots: no input was published after the report or decision date.")
    bc_path = HERE / "business_case" / "main" / "business_case_customers.csv"
    if profile == "competition" and bc_path.exists():
        bc = pd.read_csv(bc_path)
        real, spend = bc.realisable_value_eur.sum(), bc.annual_spend_eur.sum()
        v = st.columns(2)
        v[0].metric("Estimated value customers could capture · hypothetical", f"€{real / 1e6:.2f} M / year",
                    help="Synthetic data and the team's assumed realisation shares (business_case/team_params.yaml); not a demonstrated saving")
        v[0].caption(f"{100 * real / spend:.1f} % of {len(bc)} customers' €{spend / 1e6:.1f} M waste spend · median "
                     f"€{(bc.realisable_value_eur / bc.n_devices / 12).median():.0f} per device per month")
        v[1].metric("How Europress earns", "SMART subscription + weighing")
        v[1].caption("Per-device monthly Service Audit fee (scenarios €15/30/45), weighing standard on new machines, "
                     "selective retrofit; outcome-based pilot. Details: docs/Business_Case_Part2.pdf")
    st.subheader("Three findings, in plain words")
    st.markdown("""
1. **Outdated vehicle tares bias the operator's weights.** About half of the weighbridge tickets use a *stored* tare.
   Comparing it with the same truck's *weighed* tares reveals the error — every load weighed with that stale stored tare
   is off by the same amount (loads where the tare was actually weighed are not affected).
2. **Most "forgotten invoice" alarms are not forgotten.** The lift was billed under a mistyped job reference
   (two digits swapped, or a stray "X"). A flag is cleared only when an invoice line of the same contract and day
   carries a typo of *that* job's reference, one line per job; a second lift that day stays flagged.
3. **Actions are valued, not guessed.** Dispute, request weighbridge data, renegotiate or tender: each proposal shows
   its expected € value and its evidence, and waits for a person to approve it.
""")
    t = pd.DataFrame({"Task": ["B2 scorecard (0–100)", "C2 regret €/contract", "B macro-F1"],
                      "Baseline": [b2["B5 (baseline)"], c2["B6 (baseline)"]["mean_regret_eur"], b["hybrid ML+rules (baseline)"]],
                      "Ours": [b2[KB2], c2[KC2]["mean_regret_eur"], b[KB]]})
    st.dataframe(t, hide_index=True, width="stretch")

# ------------------------------------------------------------------ 2 Customer audit
elif page.startswith("2"):
    st.title("Customer audit")
    rank = fnd.groupby("customer_id").eur_delta.apply(lambda s: s.clip(lower=0).sum()).sort_values(ascending=False)
    opts = list(rank.index) + [c for c in cus.customer_id if c not in rank.index]
    cid = st.selectbox("Customer (sorted by documented overbilling)", opts, format_func=lambda c: f"{names.get(c, c)}  ({c})")
    cc = col[col.customer_id == cid]
    done = cc[cc.status.isin(["COMPLETED", "PARTIAL"])]
    ff = fnd[fnd.customer_id == cid]
    k = st.columns(5)
    k[0].metric("Lifts", len(done))
    k[1].metric("Tonnes (known mass)", f"{done.mass_kg.sum() / 1000:.1f}")
    k[2].metric("Collection cost (all lifts) · estimated", f"{done.collection_cost_eur.sum():,.0f} €")
    known = done[done.mass_kg.notna() & (done.mass_kg > 0)]
    unknown = done[~done.index.isin(known.index)]
    cpt, _, _ = cost_per_tonne_known(done)                                       # known-mass lifts only
    k[3].metric("Collection €/t (known-mass lifts)", "n/a" if np.isnan(cpt) else f"{cpt:,.0f}",
                help=f"{len(unknown)} lifts with unknown mass ({unknown.collection_cost_eur.sum():,.0f} €) are excluded from both cost and tonnes")
    k[4].metric("Documented overbilling · observed vs estimated", f"{ff.eur_delta.clip(lower=0).sum():,.0f} €")
    st.caption("Mass basis: " + ", ".join(f"{a}: {n}" for a, n in done.mass_basis.value_counts().items()) +
               f" · {len(unknown)} lifts without any mass source ({unknown.collection_cost_eur.sum():,.0f} € cost) are left out of €/t, never imputed. Prices are hypothetical customer–operator tariffs.")

    left, right = st.columns(2)
    with left:
        st.subheader("€/t per device vs comparable contracts")
        g = known.groupby(["device_id", "material_stream"]).agg(cost=("collection_cost_eur", "sum"), kg=("mass_kg", "sum"),
                                                                bench=("benchmark_eur_per_t", "median")).reset_index()
        g["eur_per_t"] = g.cost / (g.kg / 1000)
        g["ratio"] = g.eur_per_t / g.bench
        show_all = st.checkbox("Show all devices", value=False, key="all_devices")
        g = g.sort_values("ratio", ascending=False)
        if not show_all:
            g = g.head(10)
        if len(g):
            base = alt.Chart(g).encode(y=alt.Y("device_id:N", title=None, sort=list(g.device_id)))
            st.altair_chart(base.mark_bar().encode(x=alt.X("eur_per_t:Q", title="collection €/t"), color="material_stream:N",
                                                    tooltip=["device_id", "material_stream", alt.Tooltip("eur_per_t:Q", format=".0f"),
                                                             alt.Tooltip("bench:Q", format=".0f", title="benchmark €/t")])
                            + base.mark_tick(color="black", thickness=3, size=18).encode(x="bench:Q"), width="stretch")
            st.caption(("All devices" if show_all else "Top 10 devices by €/t relative to comparable contracts") +
                       ". Black tick = benchmark €/t of comparable contracts (known-mass lifts only).")
    with right:
        st.subheader("Operator weight vs reconstructed estimate")
        w = done.dropna(subset=["allocated_net_kg", "true_net_est_kg"])
        if len(w):
            st.altair_chart(alt.Chart(w).mark_circle(size=40, opacity=0.6).encode(
                x=alt.X("true_net_est_kg:Q", title="tare-corrected mass (kg, estimated)"),
                y=alt.Y("allocated_net_kg:Q", title="operator net on ticket (kg, observed)"),
                color=alt.condition("abs(datum.err_kg) > 50", alt.value("#d62728"), alt.value("#1f77b4")),
                tooltip=["collection_id", "device_id", "allocated_net_kg", alt.Tooltip("true_net_est_kg:Q", format=".0f"),
                         alt.Tooltip("err_kg:Q", format=".0f")]), width="stretch")
            st.caption(f"The x-axis is reconstructed from the operator's own tickets (gross minus the truck's weighed tare), "
                       f"not an independent hardware weighing. Red: difference > 50 kg. Net difference on shared tickets: "
                       f"{w.err_kg.sum():+,.0f} kg ({100 * w.err_kg.sum() / max(w.true_net_est_kg.sum(), 1):+.2f} %).")
        else:
            st.info("No shared weighbridge tickets for this customer.")

    st.subheader(f"Findings ({len(ff)})")
    fam = st.multiselect("Filter", sorted(ff.family.unique()), default=[])
    show = ff[ff.family.isin(fam)] if fam else ff
    cols = ["family", "what", "side", "likely_cause", "device_id", "when", "eur_delta", "detail"] + (["calculation"] if "calculation" in show else []) + ["evidence_tag", "entity_id"]
    cols = [c for c in cols if c in show.columns]
    show = show.sort_values("eur_delta", ascending=False, na_position="last")
    st.dataframe(show[cols], hide_index=True, width="stretch")
    money = show.dropna(subset=["eur_delta"])
    if len(money) and "calculation" in money:
        pick = st.selectbox("Explain a finding", list(money.entity_id.head(50)),
                            format_func=lambda e: f"{e} · {money.set_index('entity_id').at[e, 'family']} · "
                                                  f"{money.set_index('entity_id').at[e, 'eur_delta']:+,.2f} €")
        row = money.set_index("entity_id").loc[pick]
        with st.container(border=True):
            st.markdown(f"**{row.family}** — {row.what}")
            st.markdown(f"Invoice line: {row.detail}")
            st.markdown(f"Calculation: {row.calculation}")
            st.caption(f"Evidence: {row.evidence_type}. Contract rules: the customer–operator contract version in force on the service date.")
    if "side" in ff:
        sides = ff.side.fillna("UNATTRIBUTED").value_counts()
        st.caption("Discrepancies, not accusations. Who or what likely caused them: " + ", ".join(f"{k} {v}" for k, v in sides.items()) +
                   ". OPERATOR = operator data (e.g. stale stored truck tare), DEVICE = our own sensor, LOGISTICS = side waste or a shared truck (no fault), "
                   "DATA_ENTRY = mistyped references, BILLING = invoice lines that differ from the contract.")

# ------------------------------------------------------------------ 3 Action inbox
elif page.startswith("3"):
    st.title("Action inbox — proposals awaiting approval")
    prop = ev[ev.proposed].copy()
    custs = ["All"] + sorted(prop.customer_id.dropna().unique(), key=lambda c: -prop[prop.customer_id == c].expected_value_eur.sum())
    cid = st.selectbox("Customer", custs, format_func=lambda c: c if c == "All" else f"{names.get(c, c)} ({c})")
    acts = st.multiselect("Action types", sorted(prop.action.unique()), default=sorted(prop.action.unique()))
    p = prop[prop.action.isin(acts)]
    if cid != "All":
        p = p[p.customer_id == cid]
    p = p.sort_values("expected_value_eur", ascending=False)
    # decisions are keyed by (dataset, case, action) and store their own copy of the proposal, so switching the
    # dataset can never show or export a decision on a different proposal
    mine = {k: v for k, v in st.session_state.decisions.items() if k[0] == profile}
    key = lambda r: (profile, r.case_id, r.action)  # noqa: E731
    a, b_, c_ = st.columns(3)
    a.metric("Open proposals", int(sum(key(r) not in mine for r in p.itertuples())))
    b_.metric("Sum of proposal expected values", f"{p.expected_value_eur.sum():,.0f} €",
              help="Each proposal is valued on its own. Not a verified or additive saving: proposals for one contract can overlap.")
    c_.metric(f"Decided ({profile})", len(mine))
    st.caption("Demo: decisions are kept in this browser session only. Download the decision log below; a product would store them with user, time and undo.")
    top_n = st.select_slider("Show top proposals by expected value", options=[5, 10, 25, 50, 100], value=10)
    st.caption("Renegotiate and tender are alternatives: for a contract only the better of the two is proposed.")
    for r in p.head(top_n).itertuples():
        k = key(r)
        wid = f"{profile}|{r.case_id}|{r.action}"
        with st.container(border=True):
            x1, x2, x3 = st.columns([5, 1, 1])
            x1.markdown(f"**{r.action.replace('_', ' ').title()}** · {r.contract_id} · {names.get(r.customer_id, r.customer_id)} · "
                        f"operator {r.operator_id}  \nExpected value **{r.expected_value_eur:,.0f} €** — {r.evidence}")
            if hasattr(r, "ev_low_eur") and pd.notna(r.ev_low_eur):
                x1.caption(f"Range {r.ev_low_eur:,.0f} – {r.ev_high_eur:,.0f} € · inputs estimated, valuation rules hypothetical")
            if isinstance(getattr(r, "calculation", ""), str) and r.calculation:
                with x1.expander("View calculation"):
                    st.write(r.calculation)
                    if isinstance(getattr(r, "uncertainty", ""), str) and r.uncertainty:
                        st.write(r.uncertainty)
                    st.caption("Parameters: configs/assumptions.yaml → operator_actions (published, hypothetical).")
            d = mine.get(k)
            rec = {"dataset": profile, "case_id": r.case_id, "action": r.action, "contract_id": r.contract_id,
                   "customer_id": r.customer_id, "operator_id": r.operator_id, "expected_value_eur": r.expected_value_eur,
                   "evidence": r.evidence, "decided_at_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
            if d:
                x2.success(d["decision"])
                if x3.button("Undo", key=f"u|{wid}"):
                    st.session_state.decision_events.append({**d, "decision": "REVERSED", "previous_decision": d["decision"],
                                                             "decided_at_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")})
                    del st.session_state.decisions[k]; st.rerun()
            elif x2.button("Approve", key=f"a|{wid}"):
                st.session_state.decisions[k] = {**rec, "decision": "APPROVED"}
                st.session_state.decision_events.append(st.session_state.decisions[k]); st.rerun()
            if not d and x3.button("Reject", key=f"r|{wid}"):
                st.session_state.decisions[k] = {**rec, "decision": "REJECTED"}
                st.session_state.decision_events.append(st.session_state.decisions[k]); st.rerun()
    if len(p) > top_n:
        st.caption(f"Showing the top {top_n} of {len(p)} proposals.")
    if st.session_state.decision_events:
        log = pd.DataFrame(st.session_state.decision_events)
        st.download_button("Download decision log (CSV, all datasets, append-only incl. reversals)", log.to_csv(index=False), "decision_log.csv")
    st.caption("Reversal path: any decision can be undone before anything is sent; the log keeps the original decision and the reversal.")
    st.caption("Valuation rules: configs/assumptions.yaml → operator_actions (published, hypothetical). Nothing is sent to an operator without approval.")

# ------------------------------------------------------------------ 4 Operator scorecard
elif page.startswith("4"):
    st.title("Operator performance scorecard")
    st.caption("Neutral comparison of fictional operators serving overlapping regions. Billing accuracy is measured against the customer–operator contract.")
    months = sorted(sc.month.unique())
    rng_ = st.select_slider("Months", options=months, value=(months[0], months[-1]))
    s = sc[(sc.month >= rng_[0]) & (sc.month <= rng_[1])]
    metrics = {"on_time_rate": "On-time rate", "missed_visit_rate": "Missed visits", "weighbridge_shared_7d_rate": "Weighbridge shared ≤7 d",
               "billing_overcharge_pct": "Overcharge %", "billing_undercharge_pct": "Undercharge %", "discrepant_line_rate": "Discrepant lines",
               "weight_bias_pct": "Weight bias % (operator vs true)", "median_order_to_lift_hours": "Order → lift (h)"}
    s_ev = s.copy()
    if "weight_bias_prior_used" in s_ev:
        s_ev.loc[s_ev.weight_bias_prior_used.astype(bool), "weight_bias_pct"] = np.nan   # a prior is not a measurement
    raw = s_ev.groupby("operator_id")[list(metrics)].median()
    fractions = ["on_time_rate", "missed_visit_rate", "weighbridge_shared_7d_rate", "discrepant_line_rate"]   # stored as 0–1
    percents = ["billing_overcharge_pct", "billing_undercharge_pct", "weight_bias_pct"]                     # stored as %
    agg = pd.DataFrame(index=raw.index)
    for c in metrics:
        if c in fractions:
            agg[metrics[c]] = raw[c].map(lambda v: "—" if pd.isna(v) else f"{100 * v:.1f} %")
        elif c in percents:
            agg[metrics[c]] = raw[c].map(lambda v: ("UNVERIFIABLE" if c == "weight_bias_pct" else "—") if pd.isna(v) else f"{v:+.2f} %" if c == "weight_bias_pct" else f"{v:.2f} %")
        else:
            agg[metrics[c]] = raw[c].map(lambda v: "—" if pd.isna(v) else f"{v:.1f} h")
    agg = agg.rename(columns={"Overcharge %": "Overcharge", "Undercharge %": "Undercharge", "Weight bias % (operator vs true)": "Weight bias (operator vs true)"})
    if "weight_bias_status" in s:
        agg["Weight evidence (rows)"] = s.groupby("operator_id").weight_bias_status.agg(lambda x: ", ".join(f"{k} {v}" for k, v in x.value_counts().items()))
    st.dataframe(agg, width="stretch")
    st.caption("Weight bias is UNVERIFIABLE where the operator shares no tickets and its trucks' tares cannot be checked: "
               "absence of evidence is not shown as 0 %. MEASURED = most mass has a shared ticket; MODEL_ESTIMATE = inferred from the trucks' tare habit.")
    m = st.selectbox("Metric by region", list(metrics), format_func=metrics.get, index=6)
    g = s_ev.groupby(["operator_id", "region_code"])[m].median().reset_index()
    g["value"] = g[m] * (100 if m in fractions else 1)
    unit = "%" if (m in fractions or m in percents) else "h"
    g["label"] = g["value"].map(lambda v: "n/a" if pd.isna(v) else f"{v:.1f}")
    heat = alt.Chart(g).encode(x=alt.X("region_code:N", title="Region"), y=alt.Y("operator_id:N", title=None))
    st.altair_chart(heat.mark_rect().encode(color=alt.Color("value:Q", title=f"{metrics[m]} ({unit})", scale=alt.Scale(scheme="blues")),
                                            tooltip=["operator_id", "region_code", alt.Tooltip("value:Q", format=".2f", title=unit)])
                    + heat.mark_text(fontSize=11).encode(text="label:N"), width="stretch")
    st.caption("Empty cell = the operator does not serve that region; n/a = no evidence (e.g. weight bias UNVERIFIABLE).")
    b2s = scores["task_B2_score_0_100"]
    st.caption(f"Final monthly reports (month end + 45 days, as-of snapshots). Accuracy vs simulator truth: "
               f"{b2s['ours: final report, month end + 45 d (primary)']:.1f}/100 (baseline {b2s['B5 (baseline)']:.1f}).")

# ------------------------------------------------------------------ 5 Weighing accuracy
elif page.startswith("5"):
    st.title("What weighing accuracy does the business need?")
    st.warning("**Sensitivity simulation, not a hardware test.** It shows which sensor accuracy each use case needs. "
               "Whether a real sensor reaches it is what the rig test and field pilot in the weighing concept must prove.")
    st.markdown(f"Reference: {len(ref):,} clean weighbridge tickets (single load, vehicle tare weighed — no stored tares). "
                "Each is re-measured with a candidate sensor's error model (method of `examples/weighing_accuracy_value.py`).")
    presets = {"Load cells under the container (concept, typical estimate)": 1.2,
               "Load cells, pessimistic estimate": 1.9,
               "Weld-on strain gauges (estimate)": 3.0,
               "Hydraulic pressure soft sensor (estimate)": 10.0,
               "Custom": None}
    tech = st.selectbox("Sensor technology", list(presets))
    st.caption("σ values are engineering estimates from the weighing concept's error budget, not measurements.")
    sig_pct = presets[tech] if presets[tech] is not None else st.slider("Sensor accuracy σ (% of load)", 0.5, 10.0, 1.5, 0.5)
    abs_kg = st.slider("Absolute floor σ (kg)", 5, 50, 15, 5)

    def evaluate(s_pct, seed=1):
        m = ref; rng = np.random.default_rng(seed)
        sig = np.maximum(abs_kg, s_pct / 100 * m)
        dev = m + rng.normal(0, 1, len(m)) * sig
        tot = np.sqrt(sig ** 2 + 12.0 ** 2)
        band = (m >= 2500) & (m <= 3500)
        return dict(sigma=s_pct, within_100kg=float((np.abs(dev - m)[band] <= 100).mean()),
                    detect_10pct=float(((1.10 * m - dev) > 2 * tot).mean()), false_alarm=float(((m - dev) > 2 * tot).mean()),
                    eur_t_err=float(np.median(np.abs(m / dev - 1)) * 100))
    cur = evaluate(sig_pct)
    k = st.columns(4)
    k[0].metric("2.5–3.5 t loads within ±100 kg", f"{cur['within_100kg']:.0%}", help="Challenge target ≈ 95 %")
    k[1].metric("Detects +10 % tonnage overbilling", f"{cur['detect_10pct']:.0%}")
    k[2].metric("False alarms on correct invoices", f"{cur['false_alarm']:.1%}")
    k[3].metric("Median relative error of €/t", f"{cur['eur_t_err']:.2f} %",
                help="Median |reference mass / device mass − 1|: how far a cost-per-tonne figure computed from the device weight is off")
    curve = pd.DataFrame([evaluate(s) for s in np.arange(0.5, 10.01, 0.5)])
    long = curve.melt("sigma", ["within_100kg", "detect_10pct"], var_name="metric", value_name="share")
    st.altair_chart(alt.Chart(long).mark_line(point=True).encode(x=alt.X("sigma:Q", title="sensor σ (% of load)"),
                    y=alt.Y("share:Q", axis=alt.Axis(format="%")), color="metric:N")
                    + alt.Chart(pd.DataFrame({"x": [sig_pct]})).mark_rule(color="red").encode(x="x:Q"), width="stretch")
    st.info("Reading: cost-per-tonne reporting tolerates a few %, but verifying an operator's tonnage needs σ ≲ 2 %. "
            "That is why the weighing concept uses load cells, not hydraulic pressure, as the primary mass source.")
    st.caption("Target ≈ ±100 kg on 3 t is a challenge simulation target, not a Europress specification. Device weight is not a billing basis today.")
    docs = HERE / "docs"
    d1, d2 = st.columns(2)
    for col_, name, label in ((d1, "Weighing_Concept_Part1.pdf", "Weighing concept: design, BOM, calibration, validation (PDF)"),
                              (d2, "Business_Case_Part2.pdf", "Customer value and business case (PDF)")):
        if (docs / name).exists():
            col_.download_button(label, (docs / name).read_bytes(), name, mime="application/pdf")

# ------------------------------------------------------------------ 7 Lift audit trail
elif page.startswith("7"):
    st.title("Lift audit trail")
    st.caption("Row-level trace for one lift: job reference → weighbridge ticket → contract version in force → expected charges → billed lines. "
               "Every block is tagged observed, estimated or hypothetical.")
    need = ["trail_tickets.parquet", "trail_expected_lines.parquet", "trail_invoice_lines.parquet", "trail_contract_versions.parquet"]
    if not all((OUT / n).exists() for n in need):
        st.error("Run run_solution.py again to create the audit-trail tables."); st.stop()
    tk = pd.read_parquet(OUT / "trail_tickets.parquet")
    exl = pd.read_parquet(OUT / "trail_expected_lines.parquet")
    inl = pd.read_parquet(OUT / "trail_invoice_lines.parquet")
    cvs = pd.read_parquet(OUT / "trail_contract_versions.parquet")
    cz = pd.read_parquet(OUT / "trail_causes.parquet") if (OUT / "trail_causes.parquet").exists() else pd.DataFrame(columns=["collection_id"])
    flagged = inl[inl.family.notna()].groupby("resolved_ref").delta.sum().sort_values(ascending=False)
    lifts = col[col.status.isin(["COMPLETED", "PARTIAL"])].copy()
    ce_refs = exl.drop_duplicates("collection_id").set_index("collection_id").operator_job_ref
    lifts["job_ref"] = lifts.collection_id.map(ce_refs)
    jr = dict(zip(lifts.collection_id, lifts.job_ref))
    first = sorted([c for c, r_ in jr.items() if r_ in flagged.index], key=lambda c: -flagged.get(jr[c], 0))
    seen = set(first)
    order = first + [c for c in lifts.collection_id if c not in seen][:200]
    cid = st.selectbox("Lift (lifts with flagged invoice lines first)", order)
    L = lifts.set_index("collection_id").loc[cid]
    ref = L.job_ref
    with st.container(border=True):
        st.markdown(f"**1 · Lift** `{cid}` · job ref `{ref}` · {L.customer_id} · device {L.device_id} · operator {L.operator_id} · "
                    f"{pd.Timestamp(L.actual_at):%Y-%m-%d %H:%M} · trigger {L.trigger_type} · fill before {L.device_fill_pct_before:.0f} %  \n"
                    f"Device weight collected: {L.device_estimated_collected_kg:,.0f} kg · `observed` (device)")
    T = tk[tk.operator_job_ref == ref]
    with st.container(border=True):
        if len(T):
            t0 = T.iloc[0]
            st.markdown(f"**2 · Weighbridge ticket** · `observed` (operator, shared)  \n"
                        f"gross {t0.gross_kg:,.0f} kg − tare {t0.tare_kg:,.0f} kg ({t0.tare_method}) = net {t0.net_kg:,.0f} kg · "
                        f"{int(t0.loads_on_vehicle)} load(s) on truck → allocated {t0.allocated_net_kg:,.0f} kg")
            if pd.notna(t0.get("real_tare_kg", np.nan)) and t0.tare_method == "STORED":
                st.markdown(f"Correction · `estimated`: truck's weighed tare {t0.real_tare_kg:,.0f} kg → true net ≈ {t0.true_net_est_kg:,.0f} kg "
                            f"(stored tare off by {t0.tare_kg - t0.real_tare_kg:+,.0f} kg)")
            Cz = cz[cz.collection_id == cid]
            if len(Cz):
                st.markdown(f"Difference device − ticket: {Cz.iloc[0].diff_ticket_kg:+,.0f} kg · likely cause ({Cz.iloc[0].side}): {Cz.iloc[0].cause_text} · `estimated`")
        else:
            st.markdown("**2 · Weighbridge ticket** · not shared by the operator: mass comes from the invoice tonnage or the device (see below)")
    E_ = exl[exl.collection_id == cid]
    with st.container(border=True):
        if len(E_):
            cvid = E_.iloc[0].contract_version_id
            V = cvs[cvs.contract_version_id == cvid]
            st.markdown(f"**3 · Contract version in force** `{cvid}` · `observed` (customer's contract; prices hypothetical in this dataset)")
            if len(V):
                v0 = V.iloc[0]
                st.caption(f"pricing {v0.pricing_model} · lift fee {v0.lift_fee_cents / 100:.2f} € · haul {v0.haul_fee_cents_per_t / 100:.2f} €/t · "
                           f"processing {v0.processing_fee_cents_per_t / 100:.2f} €/t · credit share {v0.credit_share_bp / 100:.0f} % · "
                           f"valid from {pd.Timestamp(v0.effective_from):%Y-%m-%d}")
            st.markdown(f"**4 · Expected charges** · `estimated` (contract recomputation) · mass basis {E_.iloc[0].mass_basis}, "
                        f"{E_.iloc[0].mass_kg if pd.notna(E_.iloc[0].mass_kg) else float('nan'):,.0f} kg")
            st.dataframe(E_[["line_type", "quantity", "unit_price_eur", "amount_eur"]], hide_index=True, width="stretch")
    I_ = inl[inl.resolved_ref == ref]
    with st.container(border=True):
        st.markdown("**5 · Billed invoice lines** · `observed` (operator's invoice), compared with step 4")
        if len(I_):
            st.dataframe(I_[[c for c in ["invoice_id", "line_type", "operator_job_ref", "amount_eur", "exp", "family", "delta", "calculation"] if c in I_]]
                         .rename(columns={"exp": "expected_eur", "delta": "delta_eur"}), hide_index=True, width="stretch")
            st.markdown(f"Net difference on flagged lines: **{I_.delta.where(I_.family.notna(), 0).sum():+,.2f} €**")
        else:
            st.markdown("No invoice line found for this lift yet.")

# ------------------------------------------------------------------ 6 SMART integration
else:
    st.title("SMART integration pathway")
    steps = [("1", "Weight at source", "Load cells + RFID at the compactor"),
             ("2", "SMART telemetry + customer documents", "Fill, mass, status · contracts, invoices"),
             ("3", "SMART audit engine", "Recomputation, anomalies, operator scorecard, action valuation"),
             ("4", "Human approval and reporting", "Action inbox, decision log, €/t and ESG reports")]
    cols_ = st.columns(len(steps))
    for c_, (n, t, d) in zip(cols_, steps):
        with c_.container(border=True):
            st.markdown(f"**{n}. {t}**")
            st.caption(d)
    st.caption("Left to right: data flows from the device to a decision a person approves. Steps 1 and 3 are this team's additions; 2 and 4 build on what SMART already has.")
    with st.expander("Step details"):
        st.markdown("""
| Step | Where it runs | What it uses |
|---|---|---|
| 1. Weight at source | compactor controller (load cells → 24-bit ADC, RFID reader) | reading only when the press is idle; sensor zero only while the frame is empty; container tare from an RFID-keyed register, updated only on verified empty returns; unknown containers marked low-confidence |
| 2. Telemetry | existing SMART connectivity | hourly fill, mass, status (already in the SMART data model) |
| 3. Customer documents | SMART portal upload / e-invoice feed | contracts, invoices (customer-provided) |
| 4. Audit engine | SMART cloud (this code) | recomputation, refined rules, weight correction, action valuation |
| 5. Action inbox | SMART portal / app | proposals with € value + evidence → **human approves** |
| 6. Outcomes | SMART reporting | decision log, €/t trend, operator scorecard, ESG tonnage report |
""")
    with st.expander("Technical details: example API payloads (mock API, not deployed)"):
      st.subheader("Example API payloads")
      f = fnd.dropna(subset=["eur_delta"]).sort_values("eur_delta", ascending=False).head(1)
      if len(f):
          r = f.iloc[0]
          st.code(json.dumps({"GET /v1/customers/{id}/findings": [{
              "finding_id": r.entity_id, "type": r.family, "description": r.what, "eur_delta": r.eur_delta,
              "evidence": r.detail, "evidence_type": r.evidence_type, "status": "OPEN"}]}, indent=2), language="json")
      e = ev[ev.proposed].sort_values("expected_value_eur", ascending=False).head(1)
      if len(e):
          r = e.iloc[0]
          st.code(json.dumps({"POST /v1/actions/{case_id}/decision": {"case_id": r.case_id, "action": r.action,
                              "expected_value_eur": r.expected_value_eur, "evidence": r.evidence,
                              "decision": "APPROVED", "approved_by": "<customer user>"}}, indent=2), language="json")
      st.caption("Mock interface; `examples/recommendation_api_mock.py` in the data pack shows the same idea.")
