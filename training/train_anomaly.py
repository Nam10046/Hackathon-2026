"""Train an anomaly model on collected readings and export it for the backend. Owner: AI person.

    pip install -r training/requirements.txt
    python training/train_anomaly.py                      # reads the Docker Postgres on localhost
    curl -X POST http://localhost:8000/api/models/reload  # backend starts using it (or restart backend)

Learns what NORMAL readings look like (IsolationForest). Readings that look different
get an "ml_anomaly" alert. Collect a few days of normal data first — garbage in, garbage out.
Output: models/<name>/model.onnx + model.json
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from skl2onnx import to_onnx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.features import FEATURES, make_features  # noqa: E402  (same features as the live backend)

QUERY = """
SELECT r.compactor_id, r.ts, r.weight_kg, r.fill_pct,
       c.capacity_kg, c.volume_m3, m.density_max
FROM readings r
JOIN compactors c ON c.id = r.compactor_id
JOIN materials m ON m.name = c.material
ORDER BY r.compactor_id, r.ts
"""


def load_features(db_url: str) -> np.ndarray:
    rows = create_engine(db_url).connect().execute(text(QUERY)).mappings().all()
    X, prev = [], {}
    for r in rows:
        comp = {"capacity_kg": r["capacity_kg"], "volume_m3": r["volume_m3"]}
        mat = {"density_max": r["density_max"]}
        if not (-20 <= r["weight_kg"] <= r["capacity_kg"] * 1.3):
            continue  # broken sensor values are not "normal" — leave them out
        f = make_features(r["weight_kg"], r["fill_pct"], prev.get(r["compactor_id"]), comp, mat)
        prev[r["compactor_id"]] = r["weight_kg"]
        X.append([f[k] for k in FEATURES])
    return np.array(X, dtype=np.float32)


def train_and_export(X: np.ndarray, out_dir: Path, contamination: float, note: str = "") -> Path:
    model = IsolationForest(n_estimators=100, contamination=contamination, random_state=0).fit(X)
    onx = to_onnx(model, X[:1], target_opset={"": 17, "ai.onnx.ml": 3})
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "model.onnx").write_bytes(onx.SerializeToString())
    (out_dir / "model.json").write_text(json.dumps({
        "type": "anomaly",
        "input_features": FEATURES,
        "description": f"IsolationForest, contamination={contamination}. {note}".strip(),
        "trained_rows": int(len(X)),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))
    return out_dir


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="postgresql+psycopg://compactor:compactor@localhost:5432/compactor")
    p.add_argument("--name", default="anomaly_iforest")
    p.add_argument("--contamination", type=float, default=0.02, help="expected share of unusual readings")
    p.add_argument("--min-rows", type=int, default=200)
    args = p.parse_args()

    X = load_features(args.db)
    if len(X) < args.min_rows:
        raise SystemExit(f"Only {len(X)} usable readings — collect at least {args.min_rows} first.")
    out = train_and_export(X, ROOT / "models" / args.name, args.contamination, f"Trained on {len(X)} readings.")
    print(f"Saved {out}. Now: POST http://localhost:8000/api/models/reload")


if __name__ == "__main__":
    main()
