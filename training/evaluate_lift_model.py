"""How accurate is the LIVE LIFT MODEL? Owner: AI person.

    python training/evaluate_lift_model.py          # needs the engine in ./europress/ (see analytics/README.md)

Scores the exported ONNX files in models/ — exactly what the backend runs — on the public VALIDATION months
(the model never trained on them). Nothing here changes the model or its threshold.

Three set-ups, so we know what the live device must send:
  A  full SMART feed  + full model    = every live-known input the dataset has (cockpit uses this)
  B  ESP32 feed today + full model    = only weight, fill and clock, computed by backend/app/ai/live_lift.py, given to the
                                        full model — shows what goes wrong if you ignore the missing inputs
  C  ESP32 feed today + ESP32 model   = the models trained on exactly that feed (models/*_esp32) — what the
                                        backend runs live today

Also writes training/test_predictions_lift.csv: our flags for the PUBLIC TEST lift ids. The test answers are
private — the organisers can score this file; we never see the result, so we cannot tune on it.
Output: training/model_accuracy_report.json + a printed table.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.lift_features import to_vector  # noqa: E402
sys.path.insert(0, str(ROOT / "training"))
from lift_dataset import build_raw, live_matrix, to_matrix  # noqa: E402
from train_lift_model import FAMILIES, load_engine  # noqa: E402

SETUPS = {"A": ("full", "", "full SMART feed"), "B": ("esp32", "", "ESP32 feed, full model"),
          "C": ("esp32", "_esp32", "ESP32 feed, ESP32 model")}


def predict(folder: str, X: np.ndarray) -> tuple[np.ndarray, float]:
    meta = json.loads((ROOT / "models" / folder / "model.json").read_text())
    sess = ort.InferenceSession(str(ROOT / "models" / folder / "model.onnx"))
    p = np.asarray(sess.run(None, {sess.get_inputs()[0].name: X})[1])[:, 1]
    return p, float(meta["threshold"])


def scores(y: np.ndarray, flag: np.ndarray, value: np.ndarray) -> dict:
    tp, fp = int((flag & y).sum()), int((flag & ~y).sum())
    fn, tn = int((~flag & y).sum()), int((~flag & ~y).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"lifts": int(len(y)), "real_problems": int(y.sum()), "flagged": int(flag.sum()),
            "caught": tp, "false_alarms": fp, "missed": fn, "correct_ok": tn,
            "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "false_alarm_rate": round(fp / (fp + tn), 3) if fp + tn else 0.0,
            "eur_caught_share": round(float(value[flag & y].sum() / value[y].sum()), 3) if value[y].sum() > 0 else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=os.getenv("EUROPRESS_ENGINE", str(ROOT / "europress" / "Europress_SMART_Material_Value_Engine_v1.0.1")))
    ap.add_argument("--profile", default="competition")
    a = ap.parse_args()
    engine_dir = Path(a.engine)
    pub = engine_dir / "data" / a.profile / "public"
    dev_dir = pub / "labels_dev"
    compute, collection_features, *_rest = load_engine(engine_dir)
    _entity_times, _period_filter, _score_b, open_dataset = _rest[2], _rest[3], _rest[4], _rest[5]

    f = build_raw(pub, compute, collection_features, open_dataset).reset_index(drop=True)
    ent = _entity_times(dev_dir)
    va_ids = set(_period_filter(ent, dev_dir, "validation", "eval_at").entity_id)
    lab = pd.read_parquet(dev_dir / "anomaly_labels.parquet")
    va = f[f.collection_id.isin(va_ids)].reset_index(drop=True)
    month = pd.to_datetime(va.actual_at, utc=True).dt.tz_convert("Europe/Helsinki").dt.strftime("%Y-%m").to_numpy()
    # ESP32 feed = inputs computed by the live backend code from the raw readings (same as training)
    X = {"full": to_matrix(va, "full"), "esp32": live_matrix(pub, va, open_dataset)}

    report = {"validation_lifts": len(va), "setups": {k: v[2] for k, v in SETUPS.items()}, "families": {}}
    print(f"validation lifts: {len(va)}\n")
    print(f"{'problem':24s} {'set-up':26s} {'precision':>9s} {'recall':>7s} {'F1':>6s} {'caught':>7s} {'false alarms':>12s} {'missed':>7s}")
    for fam, folder in FAMILIES.items():
        pos = lab[(lab.label_family == fam) & lab.is_actionable].drop_duplicates("entity_id").set_index("entity_id")
        y = va.collection_id.isin(pos.index).to_numpy()
        value = va.collection_id.map(pos.value_at_stake_eur).fillna(0).to_numpy(dtype=float)
        fam_rep = {}
        for lvl, (feed_, suffix, _) in SETUPS.items():
            p, thr = predict(folder + suffix, X[feed_])
            flag = p >= thr
            s = scores(y, flag, value)
            if lvl in ("A", "C"):
                s["by_month"] = {m: scores(y[month == m], flag[month == m], value[month == m])
                                 for m in sorted(set(month))}
                # calibration: when the model says 60-80 %, is it right about 70 % of the time?
                bins = [0, .2, .4, .6, .8, 1.01]
                cal = []
                for lo, hi in zip(bins, bins[1:]):
                    m = (p >= lo) & (p < hi)
                    if m.sum():
                        cal.append({"model_says": f"{lo:.0%}-{min(hi, 1):.0%}", "lifts": int(m.sum()),
                                    "really_problem": round(float(y[m].mean()), 3)})
                s["calibration"] = cal
            fam_rep[lvl] = s
            print(f"{fam:24s} {lvl + ' ' + SETUPS[lvl][2]:26s} {s['precision']:9.3f} {s['recall']:7.3f} {s['f1']:6.3f} "
                  f"{s['caught']:7d} {s['false_alarms']:12d} {s['missed']:7d}")
        report["families"][fam] = fam_rep

    # flags for the public TEST lift ids (answers private; for the organisers to score)
    test_ids = set(pd.read_parquet(pub / "benchmark" / "task_ab_test_collections.parquet").collection_id)
    te = f[f.collection_id.isin(test_ids)].reset_index(drop=True)
    Xt = to_matrix(te, "full")
    out = []
    for fam, folder in FAMILIES.items():
        p, thr = predict(folder, Xt)
        out.append(pd.DataFrame({"entity_type": "collection", "entity_id": te.collection_id[p >= thr], "label_family": fam}))
    pd.concat(out).to_csv(ROOT / "training" / "test_predictions_lift.csv", index=False)
    report["test_period"] = {"lifts_scored": len(te), "flags_written": int(sum(len(o) for o in out)),
                             "file": "training/test_predictions_lift.csv", "score": "private (organisers)"}
    print(f"\ntest period: {len(te)} lifts scored, {report['test_period']['flags_written']} flags -> training/test_predictions_lift.csv")
    (ROOT / "training" / "model_accuracy_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
