"""Software checks: DST-safe report dates, same-process cache invalidation, missing-evidence semantics,
EUR/t scope, and Action Inbox decisions across datasets.   python -m pytest solution/tests -q"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from c2_actions import ROOT  # noqa: E402

PUB = ROOT / "data" / "quickstart" / "public"


@pytest.mark.parametrize("lag", [15, 45])
def test_report_date_is_local_midnight_for_every_month(lag):
    from weight_bias import TZ, report_date
    for month in pd.period_range("2025-01", "2027-12", freq="M").strftime("%Y-%m"):
        local = report_date(month, lag).tz_convert(TZ)
        expected = pd.Timestamp(month + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=lag)
        assert (local.hour, local.minute) == (0, 0), (month, local)
        assert local.tz_localize(None) == expected, (month, local)


def test_report_date_known_dst_cases():
    from weight_bias import TZ, report_date
    assert report_date("2026-02", 45).tz_convert(TZ) == pd.Timestamp("2026-04-15 00:00", tz=TZ)   # spring forward inside
    assert report_date("2026-09", 45).tz_convert(TZ) == pd.Timestamp("2026-11-15 00:00", tz=TZ)   # fall back inside


def test_fingerprint_detects_change_in_same_process(tmp_path):
    import snapshot
    src = tmp_path / "public"
    shutil.copytree(PUB, src)
    f0 = snapshot.source_fingerprint(str(src))
    wb = pd.read_parquet(src / "operations/weighbridge_tickets.parquet")
    wb.loc[wb.index[0], "net_kg"] += 1                       # one value changed, same path, no cache clearing
    wb.to_parquet(src / "operations/weighbridge_tickets.parquet")
    f1 = snapshot.source_fingerprint(str(src))
    assert f1 != f0
    meta = next((src / "metadata").glob("*.json"))
    meta.write_text(meta.read_text() + " ")                   # metadata change counts too
    assert snapshot.source_fingerprint(str(src)) != f1
    # and make_snapshot rebuilds within the same process
    cache = tmp_path / "cache"
    s1 = snapshot.make_snapshot(src, "2026-08-01", cache)
    n1 = len(pd.read_parquet(s1 / "operations/weighbridge_tickets.parquet"))
    wb.iloc[:5].to_parquet(src / "operations/weighbridge_tickets.parquet")
    s2 = snapshot.make_snapshot(src, "2026-08-01", cache)
    assert len(pd.read_parquet(s2 / "operations/weighbridge_tickets.parquet")) <= 5 < n1


def test_unverifiable_weight_bias_is_never_zero():
    from weight_bias import aggregate_bias, fill_prior
    w = pd.DataFrame({"operator_id": ["OP-X"] * 3 + ["OP-Y"] * 2, "region_code": "FI-01", "month": "2026-01",
                      "err_kg": [np.nan, np.nan, np.nan, -20.0, -10.0], "mass_kg": [1000, 2000, 1500, 1000, 1000],
                      "evidence_class": ["NONE"] * 3 + ["MEASURED"] * 2})
    agg = aggregate_bias(w).set_index("operator_id")
    assert agg.loc["OP-X", "weight_bias_status"] == "UNVERIFIABLE" and np.isnan(agg.loc["OP-X", "weight_bias_pct"])
    assert agg.loc["OP-Y", "weight_bias_status"] == "MEASURED"
    filled = fill_prior(agg.reset_index()).set_index("operator_id")
    assert bool(filled.loc["OP-X", "weight_bias_prior_used"]) and not bool(filled.loc["OP-Y", "weight_bias_prior_used"])
    assert filled.loc["OP-X", "weight_bias_pct"] == pytest.approx(agg.loc["OP-Y", "weight_bias_pct"])


def test_cost_per_tonne_uses_known_mass_lifts_only():
    from metrics import cost_per_tonne_known
    lifts = pd.DataFrame({"mass_kg": [1000, 2000, np.nan, 0], "collection_cost_eur": [100, 200, 999, 50]})
    cpt, n_unknown, c_unknown = cost_per_tonne_known(lifts)
    assert cpt == pytest.approx(100.0) and n_unknown == 2 and c_unknown == pytest.approx(1049)
    cpt0, n0, _ = cost_per_tonne_known(lifts.iloc[2:])
    assert np.isnan(cpt0) and n0 == 2


@pytest.mark.skipif(not (HERE / "outputs/competition/scores.json").exists() or not (HERE / "outputs/quickstart/scores.json").exists(),
                    reason="run run_solution.py for both datasets first")
def test_inbox_decision_stays_with_its_dataset_and_case():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(HERE / "app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio[0].set_value("3 · Action inbox").run()
    first = next(b for b in at.button if b.label == "Approve")
    first.click().run()
    assert not at.exception
    keys = list(at.session_state.decisions.keys())
    assert len(keys) == 1 and keys[0][0] == "competition"
    _, case, action = keys[0]
    rec = at.session_state.decisions[keys[0]]
    assert (rec["case_id"], rec["action"], rec["decision"]) == (case, action, "APPROVED")
    at.sidebar.selectbox[0].set_value("quickstart").run()                     # switch dataset after approving
    assert not at.exception
    assert next(m for m in at.metric if m.label.startswith("Decided")).value == "0"
    assert any(b.label.startswith("Download decision log") for b in at.get("download_button"))
    at.sidebar.selectbox[0].set_value("competition").run()
    assert next(m for m in at.metric if m.label.startswith("Decided")).value == "1"


def test_cause_attribution_is_complete_and_neutral():
    from causes import SIDE, attribute
    a = attribute(PUB)
    assert len(a) > 0 and a.cause.isin(list(SIDE)).all()
    assert (a.side == a.cause.map(SIDE)).all()
    # side waste / shared trucks are never blamed on anyone
    assert not a.loc[a.cause.isin(["SIDE_WASTE_ON_SAME_TRUCK", "COMBINED_LOAD_ALLOCATION"]), "actionable"].any()


@pytest.mark.skipif(not (HERE / "outputs/competition/scores.json").exists(), reason="run run_solution.py first")
def test_inbox_undo_keeps_an_append_only_log():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(HERE / "app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio[0].set_value("3 · Action inbox").run()
    next(b for b in at.button if b.label == "Approve").click().run()
    next(b for b in at.button if b.label == "Undo").click().run()
    assert not at.exception and len(at.session_state.decisions) == 0
    ev = at.session_state.decision_events
    assert [e["decision"] for e in ev] == ["APPROVED", "REVERSED"] and ev[1]["previous_decision"] == "APPROVED"


@pytest.mark.skipif(not (HERE / "outputs/competition/trail_invoice_lines.parquet").exists(), reason="run run_solution.py first")
def test_audit_trail_page_renders_full_chain():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(HERE / "app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio[0].set_value("7 · Lift audit trail").run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    for step in ("1 · Lift", "2 · Weighbridge ticket", "3 · Contract version", "4 · Expected charges", "5 · Billed invoice lines"):
        assert step in text, step
