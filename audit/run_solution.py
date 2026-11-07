"""SMART Service Audit — run the whole solution and score it with the official harness (public dev labels only).

python run_solution.py competition      (or quickstart)

Outputs in outputs/<profile>/:
  b2_operator_scorecard.csv     Task B2: operator x region x month scorecard
  b_anomaly_flags.csv           Task B: refined anomaly flags (rules + ML for collection families)
  c2_actions.csv                Task C2: proposed actions per contract
  c2_action_evidence.csv        Task C2/E: every candidate action with expected value and evidence (needs human approval)
  scores.json                   our scores vs the official baselines
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _engine import engine_root  # noqa: E402
ROOT = engine_root()
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "baselines"), str(HERE)]

import pandas as pd  # noqa: E402
from b1_economic_calculator import compute  # noqa: E402
from b2_rules_anomaly import collection_features, detect_collections, detect_invoices  # noqa: E402
from b5_operator_scorecard import scorecard  # noqa: E402
from b6_operator_actions import decide as b6_decide  # noqa: E402
import b4_ml_models as ml  # noqa: E402
from europress_data.evaluate import _entity_times, _period_filter, score_b, score_b2, score_c2  # noqa: E402

from billing import billing_metrics  # noqa: E402
from c2_actions import decide_causal as c2_decide_causal, line_deltas  # noqa: E402
from b2_causal import monthly_scorecard  # noqa: E402
from b_select import select as select_b  # noqa: E402
from export_demo import export  # noqa: E402
from flags import refine_flags  # noqa: E402
from weight_bias import job_errors, weight_bias  # noqa: E402

K = ["operator_id", "region_code", "month"]
INV_FAMS = ["OUTDATED_TARIFF", "DUPLICATE_LINE", "WRONG_SURCHARGE", "WEIGHT_BASIS_MISMATCH", "UNMATCHED_LINE",
            "MISSING_LINE", "UNINVOICED_COLLECTION", "REJECTED_LOAD"]


def main(profile="competition"):
    t0 = time.time()
    pub = ROOT / "data" / profile / "public"
    dev = pub / "labels_dev"
    out = HERE / "outputs" / profile
    out.mkdir(parents=True, exist_ok=True)
    cache = HERE / ".snapshots"
    log = lambda m: print(f"[{time.time()-t0:.0f}s] {m}", flush=True)  # noqa: E731

    # full-sample run: used for Task B (scored per entity at its own evaluation time, as the baselines are)
    # and for the dashboard's historical view
    b1, b1l = compute(pub)
    flags = detect_invoices(pub, b1, b1l)
    rflags = refine_flags(pub, b1, flags, b1l)
    refine_flags.last_audit.to_csv(out / "b_uninvoiced_reconciliation.csv", index=False)
    f = collection_features(pub, b1)
    col = detect_collections(f)
    log("baseline calculator + flags done")

    # ---------------- Task B
    rules_b, rules_b_ref = pd.concat([col, flags]), pd.concat([col, rflags])
    col_fams = col[~col.label_family.isin(INV_FAMS)]
    sel_col, sel_report, ml_full = select_b(pub, f, col_fams)
    hyb = pd.concat([ml_full, rules_b[rules_b.label_family.isin(INV_FAMS)]])
    hyb_ref = pd.concat([ml_full, rules_b_ref[rules_b_ref.label_family.isin(INV_FAMS)]])
    final_b = pd.concat([sel_col, rules_b_ref[rules_b_ref.label_family.isin(INV_FAMS)]])
    sB = {k: score_b(v, dev, "validation")["macro_f1"] for k, v in
          {"B2_rules (baseline)": rules_b, "hybrid ML+rules (baseline)": hyb, "refined rules (ours)": rules_b_ref,
           "always-ML hybrid + refined rules (ours)": hyb_ref, "per-family ML/rules selection (ours, primary)": final_b}.items()}
    final_b.to_csv(out / "b_anomaly_flags.csv", index=False)
    sel_report.to_csv(out / "b_family_selection.csv", index=False)
    log("Task B done")

    # ---------------- Task B2: monthly reports, each from the as-of snapshot of its report date
    sc_base = scorecard(pub, b1, b1l)
    b2_final = monthly_scorecard(pub, cache, log=lambda m: None, lag_days=45)
    b2_prelim = monthly_scorecard(pub, cache, log=lambda m: None, lag_days=15)
    b2_final.round(4).to_csv(out / "b2_operator_scorecard.csv", index=False)
    b2_prelim.round(4).to_csv(out / "b2_operator_scorecard_preliminary.csv", index=False)
    sB2 = {"B5 (baseline)": score_b2(sc_base, dev, "all"),
           "ours: final report, month end + 45 d (primary)": score_b2(b2_final, dev, "all"),
           "ours: final report, validation months only": score_b2(b2_final, dev, "validation"),
           "ours: preliminary report, month end + 15 d": score_b2(b2_prelim, dev, "all")}
    log("Task B2 done (as-of snapshots)")

    # ---------------- Task C2: every case decided from the as-of snapshot of its decision date
    c2, c2ev = c2_decide_causal(pub, cache, log=lambda m: None)
    c2.to_csv(out / "c2_actions.csv", index=False)
    c2ev.to_csv(out / "c2_action_evidence.csv", index=False)
    b6 = b6_decide(pub, b1, b1l, flags)
    sC2 = {"B6 (baseline)": score_c2(b6, dev, "dev"), "ours (as-of snapshots, primary)": score_c2(c2, dev, "dev")}
    log("Task C2 done (as-of snapshots)")

    je = job_errors(pub)
    ld, _ = line_deltas(pub, b1, b1l, rflags)
    export(pub, out, b1, b1l, final_b, je, ld)

    scores = {
        "profile": profile,
        "task_B_macro_f1_validation": sB,
        "task_B2_score_0_100": {k: v["scorecard_score_0_100"] for k, v in sB2.items()},
        "task_B2_per_metric_ours": {k: v for k, v in sB2["ours: final report, month end + 45 d (primary)"].items() if k.endswith(":score")},
        "task_C2_dev": {k: {m: v[m] for m in ("mean_regret_eur", "value_capture_share")} for k, v in sC2.items()},
        "task_C2_detail_ours": sC2["ours (as-of snapshots, primary)"],
        "note": "Synthetic data. Label use: Task B uses TRAIN-period labels only (to fit the baseline ML and to choose ML vs "
                "rule per family); validation/dev labels are used only for scoring, never for any choice. B2 and C2 have no "
                "parameters fitted on labels (fixed rules; C2 uses the published valuation rules). B2 and C2 are computed "
                "from as-of snapshots (the data pack's own as-of rules): no input was published after the decision or report date.",
        "runtime_seconds": round(time.time() - t0, 1),
    }
    json.dump(scores, open(out / "scores.json", "w"), indent=2, default=str)
    print(json.dumps({k: scores[k] for k in ("task_B_macro_f1_validation", "task_B2_score_0_100", "task_C2_dev")}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "competition")
