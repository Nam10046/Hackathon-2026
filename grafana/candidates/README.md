# Candidate dashboards

Files here are NOT loaded by Grafana. `grafana/dashboards` is mounted into Grafana, so a file written there goes live within seconds.

`live_pickups.json` is the proposed "Live 2 · Pickups". Build it from the generator, never by hand.

**The page states the site speed, so build it on the machine that will show it.** The generator reads `DEMO_TIME_SCALE` from
the environment, otherwise from `.env`, and prints the value it used. It must match what the backend runs with.
```bash
python grafana/make_live_pages.py --out grafana/candidates --only live_pickups
```
The committed file shows one build only. Do not copy it to a machine with a different `DEMO_TIME_SCALE`.

Applied to the local Grafana on 2026-11-07 with `DEMO_TIME_SCALE=1`. `grafana/dashboards/live_pickups.json` is that build, so a machine with another speed must rebuild first.

To apply it, after approval:
```bash
cp grafana/candidates/live_pickups.json grafana/dashboards/live_pickups.json
```
To undo: `git show 2fedaa5:grafana/dashboards/live_pickups.json > grafana/dashboards/live_pickups.json`. Grafana reloads it within seconds.
