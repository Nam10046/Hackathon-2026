"""As-of snapshots of the public package, using the data pack's OWN as-of rules (europress_data.sdk._views).

A snapshot at date D (00:00 Europe/Helsinki) keeps only what was knowable then: lifts that happened, tickets and
quality grades PUBLISHED, invoices ISSUED (dispute status hidden), contract versions in force, price indices
published, sensors installed. Every C2 decision and every monthly B2 scorecard is computed from such a snapshot,
so no derived quantity (masses, expected charges, anomaly flags, tare estimates) can carry later information.
Telemetry is not needed by these tasks and is skipped to keep snapshots small.
"""
from __future__ import annotations

import hashlib
import inspect
import shutil
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _engine import engine_root  # noqa: E402
ROOT = engine_root()
sys.path.insert(0, str(ROOT / "src"))
from europress_data.sdk import _views  # noqa: E402

SKIP = ("telemetry_hourly", "telemetry_daily_summary")
SNAPSHOT_FORMAT = "3"   # bump when the snapshot logic in this file changes


def source_fingerprint(pub: str) -> str:
    """SHA-256 over the CONTENT of every input file (all parquet tables used by the snapshot + the metadata folder),
    the as-of rules (sdk._views source) and the snapshot format. Recomputed on every call - no in-process memo - so a
    file replaced while the program runs is detected too. Cost: hashing ~120 MB, well under a second."""
    h = hashlib.sha256(SNAPSHOT_FORMAT.encode())
    h.update(inspect.getsource(_views).encode())
    root = Path(pub)
    files = [p for p in root.rglob("*") if p.is_file()]
    for p in sorted(files):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(("labels_dev", "benchmark", "telemetry")) or not (rel.endswith(".parquet") or rel.startswith("metadata/")):
            continue
        h.update(rel.encode())
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def make_snapshot(pub: Path, as_of_date: str, cache: Path) -> Path:
    """Write (once) and return a directory holding the public package as of `as_of_date` (YYYY-MM-DD)."""
    fp = source_fingerprint(str(Path(pub).resolve()))
    dest = cache / f"{Path(pub).parent.name}_asof_{as_of_date}"
    done = dest / ".complete"
    if done.exists() and done.read_text().strip() == f"{as_of_date} {fp}":
        return dest                                  # same data, same rules: reuse
    if dest.exists():
        shutil.rmtree(dest)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    for name, (rel, q) in _views(Path(pub), as_of_date).items():
        if name in SKIP or rel.startswith(("labels_dev", "benchmark")):
            continue
        d = dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY ({q}) TO '{d}' (FORMAT PARQUET)")
    con.close()
    # metadata is needed by some readers; copy it unchanged (no time-dependent content)
    if (Path(pub) / "metadata").exists():
        shutil.copytree(Path(pub) / "metadata", dest / "metadata", dirs_exist_ok=True)
    done.write_text(f"{as_of_date} {fp}")
    return dest
