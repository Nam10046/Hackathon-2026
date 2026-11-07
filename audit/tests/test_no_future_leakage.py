"""Mutation test: corrupt everything published AFTER a decision date; decisions for that date must not change.

Run:  python -m pytest solution/tests -q
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from c2_actions import ROOT, decide_causal  # noqa: E402
from b2_causal import monthly_scorecard  # noqa: E402

PUB = ROOT / "data" / "quickstart" / "public"


def _mutate(src: Path, dst: Path, cut: pd.Timestamp):
    shutil.copytree(src, dst)
    wb = pd.read_parquet(dst / "operations/weighbridge_tickets.parquet")
    late = wb.published_at >= cut
    for c in ("gross_kg", "net_kg", "allocated_net_kg"):
        wb.loc[late, c] = wb.loc[late, c] * 3
    wb.loc[late, "tare_kg"] = wb.loc[late, "tare_kg"] + 777
    wb.to_parquet(dst / "operations/weighbridge_tickets.parquet")
    inv = pd.read_parquet(dst / "finance/invoices.parquet")
    il = pd.read_parquet(dst / "finance/invoice_lines.parquet")
    late_inv = set(inv[inv.issued_at >= cut].invoice_id)
    m = il.invoice_id.isin(late_inv)
    il.loc[m, "amount_eur"] = il.loc[m, "amount_eur"] * 2 + 13
    il.to_parquet(dst / "finance/invoice_lines.parquet")
    ce = pd.read_parquet(dst / "operations/collection_events.parquet")
    lc = ce.actual_at >= cut
    ce.loc[lc, "device_estimated_collected_kg"] = ce.loc[lc, "device_estimated_collected_kg"] * 5
    ce.to_parquet(dst / "operations/collection_events.parquet")


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    cases = pd.read_parquet(PUB / "benchmark/operator_action_cases.parquet")
    as_of = cases.as_of_at.min()
    cut = as_of.tz_convert("Europe/Helsinki").normalize().tz_convert("UTC")
    base = tmp_path_factory.mktemp("w")
    mut = base / "mutated" / "public"
    _mutate(PUB, mut, cut)
    return as_of, base


def test_c2_decisions_ignore_future_data(worlds):
    as_of, base = worlds
    a, ea = decide_causal(PUB, base / "cache_a", log=lambda m: None)
    b, eb = decide_causal(base / "mutated" / "public", base / "cache_b", log=lambda m: None)
    ids = set(pd.read_parquet(PUB / "benchmark/operator_action_cases.parquet").query("as_of_at == @as_of").case_id)
    pa = a[a.case_id.isin(ids)].sort_values("case_id").reset_index(drop=True)
    pb = b[b.case_id.isin(ids)].sort_values("case_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(pa, pb)
    va = ea[ea.case_id.isin(ids)].sort_values(["case_id", "action"]).reset_index(drop=True)
    vb = eb[eb.case_id.isin(ids)].sort_values(["case_id", "action"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(va.drop(columns="snapshot_date"), vb.drop(columns="snapshot_date"))


def test_b2_month_ignores_data_after_its_report_date(tmp_path):
    from weight_bias import TZ, report_date
    ce = pd.read_parquet(PUB / "operations/collection_events.parquet", columns=["scheduled_at"])
    first = sorted(ce.scheduled_at.dt.tz_convert(TZ).dt.strftime("%Y-%m").unique())[0]
    cut_local = report_date(first, 15).tz_convert(TZ).normalize() + pd.Timedelta(days=1)
    _mutate(PUB, tmp_path / "mut" / "public", cut_local.tz_convert("UTC"))
    sa = monthly_scorecard(PUB, tmp_path / "cache_c", log=lambda m: None, lag_days=15)
    sb = monthly_scorecard(tmp_path / "mut" / "public", tmp_path / "cache_d", log=lambda m: None, lag_days=15)
    cut = cut_local.strftime("%Y-%m-%d")
    early = sa[sa.report_date < cut].month.unique()
    assert len(early) > 0
    xa = sa[sa.month.isin(early)].sort_values(["month", "operator_id", "region_code"]).reset_index(drop=True)
    xb = sb[sb.month.isin(early)].sort_values(["month", "operator_id", "region_code"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(xa, xb)


def test_report_date_cutoffs():
    from weight_bias import TZ, report_date
    assert report_date("2026-01", 15).tz_convert(TZ) == pd.Timestamp("2026-02-16 00:00", tz=TZ)
    assert report_date("2026-01", 45).tz_convert(TZ) == pd.Timestamp("2026-03-18 00:00", tz=TZ)
    # a lift at the last minute of the month with the maximum 45-day ticket lag is inside the final cut
    last_ticket = pd.Timestamp("2026-01-31 23:59", tz=TZ) + pd.Timedelta(days=45)
    assert last_ticket < report_date("2026-01", 45)
    assert last_ticket + pd.Timedelta(days=1) >= report_date("2026-01", 45)


def test_snapshot_cache_rebuilds_when_source_changes(tmp_path):
    import snapshot
    src = tmp_path / "w" / "public"
    shutil.copytree(PUB, src)
    cache = tmp_path / "cache"
    day = "2026-08-01"
    s1 = snapshot.make_snapshot(src, day, cache)
    n1 = len(pd.read_parquet(s1 / "operations/weighbridge_tickets.parquet"))
    wb = pd.read_parquet(src / "operations/weighbridge_tickets.parquet")
    wb.iloc[:10].to_parquet(src / "operations/weighbridge_tickets.parquet")     # change the source
    s2 = snapshot.make_snapshot(src, day, cache)
    n2 = len(pd.read_parquet(s2 / "operations/weighbridge_tickets.parquet"))
    assert n2 != n1 and n2 <= 10
