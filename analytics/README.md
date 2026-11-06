# Analytics: Customer Value Cockpit from the Europress dataset

Turns the official synthetic dataset (≈500 compactors × 365 days) into findings, issues, an operator scorecard and
recommended actions, using the organisers' calculators (B1, B2, B5, B6) + **our live lift model** (early / late lifts,
`models/lift_*`) + our evidence layer.

## Setup (once per laptop)
1. Unzip `Europress_SMART_Material_Value_Engine_v1.0.1_PARTICIPANTS.zip` into the repo folder `europress/`, so this exists:
   `europress/Europress_SMART_Material_Value_Engine_v1.0.1/data/competition/public/`
   (`europress/` is git-ignored — the dataset is not committed.)

## Build the cockpit (≈1 minute)
```powershell
docker compose up -d                 # the server must run
docker compose run --rm analytics    # reads the dataset, writes cp_* tables
```
Then open:
- **Grafana → Customer Value Cockpit**: http://localhost:3000/d/value-cockpit
- **Approve / reject proposals**: http://localhost:8000/cockpit

Quick test with the small dataset: `docker compose run --rm analytics python analytics/build_cockpit.py --profile quickstart`

## Tables written
| Table | One row per | Evidence |
|---|---|---|
| `cp_collections` | lift: contract economics, €/t, mass source | mass: OBSERVED (weighbridge/invoice) or ESTIMATED (device) |
| `cp_flags` | finding (collection or invoice line) + plain-language explanation + € at stake + `detected_by` (rules / live lift model) | ESTIMATED |
| `cp_issues` | **issue** = same problem on the same compactor, counted once (times seen, first/last seen, total €) | ESTIMATED |
| `cp_scorecard` | operator × region × month | from the customer's own records |
| `cp_actions` | proposed action per contract (dispute / request data / renegotiate / tender) | needs human approval |
| `action_decisions` | approve / reject / revert, who and when | written by the backend, never deleted |

## Where to improve (beats the baselines → better score)
See the engine's `docs/BENCHMARK.md` → "Known failure cases". Score yourself on validation:
`python baselines/run_all.py competition` inside the engine folder.
