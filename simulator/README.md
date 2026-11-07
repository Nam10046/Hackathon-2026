# Simulator — test the live system with known answers

We have no load cell yet, so this program pretends to be compactors. It makes **good and bad data** and writes
down the **right answer** for every event, so we can grade the system like an exam.

```powershell
python simulator/simulate.py grade                        # 24 compactors x 75 days, scorecard 0-100 (~3 min)
python simulator/simulate.py grade --seed 2 --devices 30 --days 90   # a different, unseen world
python simulator/simulate.py live --hours 72 --faults     # feed C1-C3 into the running backend -> Grafana "6 Live sensors"
```

| What it simulates | Right answer the system should give |
|---|---|
| Normal emptying at 70–92 % | `emptied`, no other alert |
| **Too early**: emptied at 12–38 %, no reason | `ml_premature_unjustified` |
| **Justified early**: low fill but the hygiene maximum (days) reached — a trap | must NOT be flagged |
| **Too late**: sat ≥ 97 % full for 28–80 h | `ml_delayed_collection` |
| Spike (one reading +35–60 % of capacity) | `spike` |
| Impossible value (−150 kg or 160 % of capacity) | `sensor_fault` |
| Stuck sensor (same value 8–20 h) | `sensor_stuck` |
| Missing data (4–12 h nothing) | `data_gap` |
| Slow drift (+3 kg/h for 3 days) | `zero_shift` after the next emptying |
| Glitch (one reading ≈ 0 while the fill sensor says full) | must NOT count as an emptying |
| Duplicate message | stored once, no double alert |
| Heavy / wrong material (2× the weight for its fill) | `contamination` or `overload` |

The scorecard: lift detection 25 %, too early 15 %, too late 15 %, justified lifts left alone 5 %, bad data noticed
25 %, few false alarms 15 % (1 false alarm per compactor-week = 0 points for that part).

**Honesty rule:** this is our own world with simple physics. We use it to find weak spots in the live pipeline and
fix the rules, then check the fix on **new seeds** and on the **real Europress replay** (`training/replay_live.py`).
We never train the AI model on simulator data. "Too late" in the dataset also includes "came long after the order
level", so the scorecard shows two definitions.
