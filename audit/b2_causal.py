"""Task B2 as monthly reports, each built ONLY from the as-of snapshot of its report date.

A month's FINAL scorecard is cut at the end of the 45th day after month end, when the operators' ticket-sharing
window (at most 45 days) has closed; a PRELIMINARY one can be issued after 15 days (lag_days=15), when invoices are out. Every input to
that month's row (Baseline-1 recomputation, invoice flags, billing deltas, tare estimates, punctuality) is
recomputed from the snapshot of that date, so a row never uses tickets or invoices published later.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _engine import engine_root  # noqa: E402
ROOT = engine_root()
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "baselines"), str(HERE)]
from b1_economic_calculator import compute  # noqa: E402
from b2_rules_anomaly import detect_invoices  # noqa: E402
from b5_operator_scorecard import scorecard  # noqa: E402

from billing import billing_metrics  # noqa: E402
from flags import refine_flags  # noqa: E402
from snapshot import make_snapshot  # noqa: E402
from weight_bias import TZ, aggregate_bias, fill_prior, job_errors, report_date  # noqa: E402

K = ["operator_id", "region_code", "month"]
DROP = ["weight_bias_pct", "billing_overcharge_pct", "billing_undercharge_pct", "discrepant_line_rate"]


def monthly_scorecard(pub: Path, cache: Path, log=print, lag_days: int = 45) -> pd.DataFrame:
    ce = pd.read_parquet(pub / "operations" / "collection_events.parquet", columns=["scheduled_at"])
    months = sorted(ce.scheduled_at.dt.tz_convert(TZ).dt.strftime("%Y-%m").unique())
    rows = []
    for m in months:
        rd = report_date(m, lag_days).tz_convert(TZ)
        snap = make_snapshot(pub, rd.strftime("%Y-%m-%d"), cache)
        b1, b1l = compute(snap)
        fl = refine_flags(snap, b1, detect_invoices(snap, b1, b1l), b1l)
        sc = scorecard(snap, b1, b1l)
        sc = sc[sc.month == m].drop(columns=DROP)
        bm = billing_metrics(snap, b1, b1l, fl, keep_outdated="keep")
        w = job_errors(snap)
        wb = fill_prior(aggregate_bias(w[w.month == m]))
        rows.append(sc.merge(wb, on=K, how="left").merge(bm[bm.month == m], on=K, how="left").assign(report_date=rd.strftime("%Y-%m-%d")))
        log(f"  B2 {m}: report date {rd:%Y-%m-%d}, {len(rows[-1])} rows")
    return pd.concat(rows, ignore_index=True)
