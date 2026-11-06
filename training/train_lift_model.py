"""Train the LIVE LIFT MODEL on the Europress dataset and export it for the backend. Owner: AI person.

    python training/train_lift_model.py              # engine in ./europress/ (see analytics/README.md)

What it learns: at the moment a compactor is emptied, was this lift
  - PREMATURE_UNJUSTIFIED  (too early, no hygiene / contract reason -> wasted money), or
  - DELAYED_COLLECTION     (container sat full too long -> overflow / side-waste risk)?
Inputs: only what the device knows live (backend/app/ai/lift_features.py). No tickets, invoices, prices.

Honest evaluation: trained on the dataset's TRAIN months, threshold chosen on the last part of TRAIN,
scored on the public VALIDATION months with the organisers' scorer, compared with their rule baseline (B2).
Writes models/lift_premature/ and models/lift_delayed/ (model.onnx + model.json) and training/lift_model_report.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.lift_features import FEATURES  # noqa: E402
sys.path.insert(0, str(ROOT / "training"))
from lift_dataset import build_raw, to_matrix  # noqa: E402

FAMILIES = {"PREMATURE_UNJUSTIFIED": "lift_premature", "DELAYED_COLLECTION": "lift_delayed"}
ALERT_TEXT = {
    "PREMATURE_UNJUSTIFIED": "This lift looks unnecessary (container not full, no hygiene/contract reason)",
    "DELAYED_COLLECTION": "This lift came late (container was full for long) — overflow / side-waste risk",
}


def load_engine(engine_dir: Path):
    sys.path.insert(0, str(engine_dir / "src"))
    sys.path.insert(0, str(engine_dir / "baselines"))
    from b1_economic_calculator import compute
    from b2_rules_anomaly import collection_features, detect_collections, detect_invoices
    from europress_data.evaluate import _entity_times, _period_filter, score_b
    from europress_data.sdk import open_dataset
    return compute, collection_features, detect_collections, detect_invoices, _entity_times, _period_filter, score_b, open_dataset


def best_threshold(y, p) -> float:
    grid = np.linspace(0.1, 0.9, 33)
    return float(grid[int(np.argmax([f1_score(y, p >= t, zero_division=0) for t in grid]))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=os.getenv("EUROPRESS_ENGINE", str(ROOT / "europress" / "Europress_SMART_Material_Value_Engine_v1.0.1")))
    ap.add_argument("--profile", default="competition")
    ap.add_argument("--no-export", action="store_true")
    a = ap.parse_args()
    engine_dir = Path(a.engine)
    pub = engine_dir / "data" / a.profile / "public"
    dev_dir = pub / "labels_dev"
    eng = load_engine(engine_dir)
    compute, collection_features, detect_collections, detect_invoices, _entity_times, _period_filter, score_b, _ = eng

    f = build_raw(pub, compute, collection_features, eng[-1])
    X = to_matrix(f)
    ids = f.collection_id.to_numpy()
    ent = _entity_times(dev_dir)
    tr_ids = set(_period_filter(ent, dev_dir, "train", "eval_at").entity_id)
    va_ids = set(_period_filter(ent, dev_dir, "validation", "eval_at").entity_id)
    tr, va = np.isin(ids, list(tr_ids)), np.isin(ids, list(va_ids))
    lab = pd.read_parquet(dev_dir / "anomaly_labels.parquet")
    order = f.actual_at.to_numpy()
    print(f"lifts: {len(f)} · train {tr.sum()} · validation {va.sum()} · features {len(FEATURES)}")

    model_preds, report = [], {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "families": {}}
    for fam, folder in FAMILIES.items():
        pos = set(lab[(lab.label_family == fam) & lab.is_actionable].entity_id)
        y = np.isin(ids, list(pos)).astype(int)
        # threshold: fit on the first 75 % of TRAIN (by time), tune on the last 25 % of TRAIN
        tr_idx = np.where(tr)[0]
        tr_idx = tr_idx[np.argsort(order[tr_idx])]
        cut = int(len(tr_idx) * 0.75)
        fit_i, tune_i = tr_idx[:cut], tr_idx[cut:]
        params = dict(n_estimators=300, learning_rate=0.05, max_depth=4, subsample=0.8, random_state=0)
        m = GradientBoostingClassifier(**params).fit(X[fit_i], y[fit_i])
        thr = best_threshold(y[tune_i], m.predict_proba(X[tune_i])[:, 1])
        model = GradientBoostingClassifier(**params).fit(X[tr], y[tr])      # final: all train months
        p_va = model.predict_proba(X[va])[:, 1]
        flagged = ids[va][p_va >= thr]
        model_preds.append(pd.DataFrame({"entity_type": "collection", "entity_id": flagged, "label_family": fam}))
        report["families"][fam] = {"threshold": round(thr, 3), "train_rows": int(tr.sum()), "train_positives": int(y[tr].sum())}
        print(f"{fam}: threshold {thr:.2f}, train positives {y[tr].sum()}")

        if not a.no_export:
            from skl2onnx import to_onnx
            onx = to_onnx(model, X[:1], target_opset={"": 17, "ai.onnx.ml": 3}, options={id(model): {"zipmap": False}})
            out = ROOT / "models" / folder
            out.mkdir(parents=True, exist_ok=True)
            (out / "model.onnx").write_bytes(onx.SerializeToString())
            (out / "model.json").write_text(json.dumps({
                "type": "lift_classifier", "family": fam, "input_features": FEATURES, "threshold": round(thr, 3),
                "alert_message": ALERT_TEXT[fam],
                "description": "Gradient boosting on live-only lift features (lift_features.py). Trained on the Europress "
                               "synthetic dataset, train months only. Advice for a human, not a decision.",
                "trained_rows": int(tr.sum()), "created": report["created"]}, indent=2))
            import onnxruntime as ort                                        # check ONNX == scikit-learn
            sess = ort.InferenceSession(str(out / "model.onnx"))
            onnx_p = sess.run(None, {sess.get_inputs()[0].name: X[va][:500]})[1][:, 1]
            report["families"][fam]["onnx_max_abs_diff"] = float(np.abs(onnx_p - p_va[:500]).max())

    # ---- score on VALIDATION with the organisers' scorer: rules alone vs rules + our model ----
    b1, b1l = compute(pub)
    rules = pd.concat([detect_collections(collection_features(pub, b1)), detect_invoices(pub, b1, b1l)])
    hybrid = pd.concat([rules[~rules.label_family.isin(FAMILIES)], *model_preds])
    s_rules, s_hyb = score_b(rules, dev_dir, "validation"), score_b(hybrid, dev_dir, "validation")
    for fam in FAMILIES:
        r, h = s_rules[fam], s_hyb[fam]
        report["families"][fam]["validation"] = {
            "baseline_B2": {k: r[k] for k in ["precision", "recall", "f1", "explained_flagged_as_anomaly", "value_weighted_recall"]},
            "our_model": {k: h[k] for k in ["precision", "recall", "f1", "explained_flagged_as_anomaly", "value_weighted_recall"]}}
        print(f"{fam:24s} F1 baseline {r['f1']:.3f} -> model {h['f1']:.3f} · recall {r['recall']:.3f} -> {h['recall']:.3f} · "
              f"traps flagged {r['explained_flagged_as_anomaly']} -> {h['explained_flagged_as_anomaly']}")
    report["macro_f1"] = {"baseline_B2": s_rules["macro_f1"], "rules_plus_model": s_hyb["macro_f1"]}
    report["macro_f1_detection_only"] = {"baseline_B2": s_rules["macro_f1_detection_only"], "rules_plus_model": s_hyb["macro_f1_detection_only"]}
    print(f"macro-F1 (all families) {s_rules['macro_f1']} -> {s_hyb['macro_f1']} · detection-only "
          f"{s_rules['macro_f1_detection_only']} -> {s_hyb['macro_f1_detection_only']}")
    (ROOT / "training" / "lift_model_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
