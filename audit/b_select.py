"""Task B: choose, per anomaly family, between the ML model and the transparent rule — using the TRAIN period only.

The baseline hybrid always takes ML for collection families. On a small dataset (quickstart: 46 training days)
ML loses to the rules. Here the train period is split in time: ML is fitted on its first two thirds and both
methods are compared on the last third (per-family F1, same definition as the official scorer). A family uses
ML only if ML wins there; ties go to the rule (simpler to explain). The chosen ML families are then refitted on
the whole train period. Validation labels are never used for the choice.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _engine import engine_root  # noqa: E402
ROOT = engine_root()
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "baselines")]
import b4_ml_models as ml  # noqa: E402
from europress_data.evaluate import _entity_times  # noqa: E402

TZ = "Europe/Helsinki"


def _local(s):
    return pd.to_datetime(s, utc=True).dt.tz_convert(TZ).dt.tz_localize(None)


def window_f1(pred: pd.DataFrame, lab: pd.DataFrame, ent: pd.DataFrame, a, b, fam: str):
    """Per-family F1 in [a, b) with the official definition (actionable positives; entities evaluated in window)."""
    lw = lab[(_local(lab.eval_at) >= a) & (_local(lab.eval_at) < b)]
    ew = set(ent[(_local(ent.eval_at) >= a) & (_local(ent.eval_at) < b)].entity_id)
    pos = set(lw[(lw.label_family == fam) & lw.is_actionable].entity_id)
    pr = set(pred[(pred.label_family == fam) & pred.entity_id.isin(ew)].entity_id)
    if not pos:
        return None
    tp = len(pos & pr)
    p, r = (tp / len(pr) if pr else 0.0), tp / len(pos)
    return 2 * p * r / (p + r) if p + r else 0.0


def select(pub: Path, f: pd.DataFrame, rules_col: pd.DataFrame):
    dev = pub / "labels_dev"
    lab = pd.read_parquet(dev / "anomaly_labels.parquet")
    man = json.load(open(pub / "metadata" / "dataset_manifest.json"))["label_periods"]
    ta, tb = pd.Timestamp(man["train"][0]), pd.Timestamp(man["train"][1])
    cut = ta + (tb - ta) * 2 / 3
    ent = _entity_times(dev)
    tl = _local(f.collection_id.map(ent.set_index("entity_id").eval_at))
    lab_t = lab[_local(lab.eval_at) < tb]
    ml_inner = ml.task_b(f[tl < cut], lab[_local(lab.eval_at) < cut], f)
    ml_full = ml.task_b(f[tl < tb], lab_t, f)
    choice, report = {}, []
    for fam in sorted(set(ml_full.label_family)):
        f_ml = window_f1(ml_inner, lab_t, ent, cut, tb, fam)
        f_ru = window_f1(rules_col, lab_t, ent, cut, tb, fam)
        use_ml = f_ml is not None and f_ru is not None and f_ml > f_ru
        if f_ru is None and f_ml is not None:
            use_ml = f_ml > 0 and not (rules_col.label_family == fam).any()
        choice[fam] = "ML" if use_ml else "RULES"
        report.append({"family": fam, "f1_ml_inner": f_ml, "f1_rules_inner": f_ru, "chosen": choice[fam]})
    parts = [ml_full[ml_full.label_family.isin([k for k, v in choice.items() if v == "ML"])],
             rules_col[~rules_col.label_family.isin([k for k, v in choice.items() if v == "ML"])]]
    return pd.concat(parts, ignore_index=True), pd.DataFrame(report), ml_full
