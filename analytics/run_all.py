"""One command for the whole cockpit. Owner: data person.

    python analytics/run_all.py                 # competition dataset
    python analytics/run_all.py quickstart
    python analytics/run_all.py --refresh       # re-run the team audit even if its outputs exist

1. Team audit pipeline (audit/run_solution.py, about 4-5 min): Task B problems, Task B2 waste-company scorecard,
   Task C2 proposals, all from as-of snapshots (no data published after the decision/report date).
   Skipped when audit/outputs/<profile>/ already exists.
2. analytics/build_cockpit.py: writes the cp_* tables that Grafana and the approval page show.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
profile = args[0] if args else "competition"
out = ROOT / "audit" / "outputs" / profile / "demo_findings.csv"
if "--refresh" in sys.argv or not out.exists():
    print(f"running the team audit pipeline for {profile} (about 4-5 minutes)...", flush=True)
    subprocess.run([sys.executable, str(ROOT / "audit" / "run_solution.py"), profile], check=True)
else:
    print(f"team audit outputs found in {out.parent} (use --refresh to recompute)", flush=True)
subprocess.run([sys.executable, str(ROOT / "analytics" / "build_cockpit.py"), "--profile", profile], check=True)
