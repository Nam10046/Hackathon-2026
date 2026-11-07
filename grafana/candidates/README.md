# Candidate dashboards

Files here are NOT loaded by Grafana. `grafana/dashboards` is mounted into Grafana, so a file written there goes live within seconds.

`live_pickups.json` is the proposed "Live 2 · Pickups". Build it from the generator, never by hand:
```bash
DEMO_TIME_SCALE=60 python grafana/make_live_pages.py --out grafana/candidates --only live_pickups
```
To apply it, after approval:
```bash
cp grafana/candidates/live_pickups.json grafana/dashboards/live_pickups.json
```
To undo: `git checkout grafana/dashboards/live_pickups.json`
