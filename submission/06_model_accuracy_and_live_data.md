# Part 6 — How accurate is our model, and does it work on live data?

Short answer: **on full SMART data the model is about 92 % right (F1). On a simple ESP32 (weight + fill only) it is
about 64–78 % right.** We measured both on months the model never saw, tested the live path by playing 67,000 real
sensor readings into our backend one by one, and stress-tested it with a **simulator that injects bad data with known
answers** (section 5b): **65 → 93 points** after the fixes it revealed.

Everything below can be re-run:

```
python training/evaluate_lift_model.py          # accuracy on unseen months (about 1 min)
python training/replay_live.py --devices 40     # live test through the real backend (about 12 min; re-run to continue if stopped)
python simulator/simulate.py grade              # stress test with good and bad data, scorecard 0-100 (about 3 min)
```

## 1. What the model does

At the moment a compactor is emptied, it answers two questions:

- **Too early?** — the lift was not needed (container not full, no hygiene or contract reason) → wasted money.
- **Too late?** — the container sat full for a long time → overflow and side-waste risk.

It only uses what the device knows at that moment. No invoices, no weighbridge tickets, no prices. So it can warn
**before** the bill arrives.

## 2. How we measured accuracy (honestly)

- Trained only on the **train months** (Oct 2025 – May 2026). The cut-off for "how sure before we alert" was chosen
  on the last part of the train months.
- Scored on the **validation months** (Jun–Jul 2026), which the model never saw: 3,084 lifts.
- The organisers' **test months** are secret. We wrote our predictions to `training/test_predictions_lift.csv` so the
  organisers can score them. We cannot see the answers, so we cannot cheat.
- We test the **exact model files** the backend runs (ONNX), not a copy.

How to read the numbers:

| Word | Meaning |
|---|---|
| Precision | Of the alerts we raise, how many are real problems |
| Recall | Of the real problems, how many we catch |
| F1 | One number combining both (1.0 = perfect) |

## 3. Results on unseen months (3,084 lifts)

| What the model gets | Model | Too early: F1 | Too late: F1 |
|---|---|---|---|
| **Full SMART data** (press load, cycles, sensor status, order type, delay) | full model | **0.93** | **0.92** |
| Only weight + fill + time | full model (wrong for this input) | 0.63 | 0.28 |
| Only weight + fill + time | **ESP32 model** (trained on exactly this) | 0.75 | 0.63 |
| Only weight + fill + time + **the order level setting** (fill % at which SMART orders a truck) | **ESP32 model, final** | **0.78** | **0.64** |
| *Organisers' rule baseline B2 (uses full data)* | rules | *0.72* | *0.77* |

Details for the full-data model:

- Too early: 369 caught, 23 false alarms, 35 missed. It catches **91 % of the money at stake**.
- Too late: 440 caught, 48 false alarms, 26 missed.
- Stable across the two halves of the period (precision 0.92–0.96).
- **Its confidence is honest.** When it says "80–100 % sure", it is right 98 % of the time. When it says "below
  20 %", only 0.5 % are real problems. So the % shown in an alert can be trusted.

## 4. What changes with live data

### Problem 1: a simple ESP32 knows less
The full model relies on the order time (how long after ordering the truck came) and the press data. A basic ESP32
does not send these. Giving the full model only weight + fill makes it miss **82 % of late lifts** (row 2 above).
**Fix:** a second model pair trained on exactly what the ESP32 sends (`models/*_esp32`). The backend picks the right
pair automatically (`"feed": "esp32"`).

### Problem 2: the live numbers are computed differently ("train/serve skew")
At first we trained the ESP32 model on the organisers' ready-made numbers. Live, our backend computes those numbers
itself from raw readings, slightly differently. The test said 0.84 but live gave 0.61.
**Fix:** we now compute the training inputs **with the same live code** (`backend/app/ai/live_lift.py`) from the
raw hourly readings. Test and live now agree.

### Problem 3: real sensors are noisy
The live replay showed false "emptied" events: noise near empty (75 kg → 25 kg) and single bad readings (2,070 kg →
82 kg → 2,190 kg while the fill sensor still said 68 %).
**Fix:** an emptying now needs a real drop, and the fill sensor must agree. False emptyings went from 112 to 35.

## 5. Live test: real readings through the real backend

40 compactors from the dataset, 66,861 hourly readings, sent one by one to the backend. The backend got only
`{compactor, time, weight, fill}` plus each compactor's order-level setting — no labels, no list of lifts.

| Check | First version | **Final** |
|---|---|---|
| Real lifts the backend noticed by itself | 238 of 256 (93.0 %) | **239 of 256 (93.4 %)** |
| "Emptied" alerts with no real lift | 35 | 37 |
| Too early: precision / recall / F1 | 0.68 / 0.50 / 0.58 | 0.75 / 0.58 / **0.65** (26 real problems) |
| Too late: precision / recall / F1 | 0.67 / 0.74 / 0.70 | 0.63 / 0.89 / **0.74** (35 real problems) |

The sample is small, so these numbers move by about ±0.1. They are in the same range as section 3, which shows the
whole live chain works: sensor reading → emptying detected → inputs built → model → alert.

## 5b. Stress test: a simulator with known answers (`simulator/`)

We have no load cell, so a simulator pretends to be compactors. It writes down the **right answer** for every event:
normal, too early, too late, and **justified early lifts** (hygiene maximum reached — a trap that must not be flagged).
It also injects **bad data**: spikes, impossible values, a stuck sensor, missing hours, slow drift, single glitches,
duplicate messages and heavy/wrong material. Every reading goes through the real backend code.

| Part (weight) | First run | After fixes |
|---|---:|---:|
| Lift detection (25 %) | 0.986 | **0.995** |
| Too early (15 %) | 0.928 | 0.909 |
| Too late (15 %) | 0.673 | 0.660 |
| Justified lifts left alone (5 %) | 0.913 | 0.957 |
| **Bad data noticed (25 %)** | **0.484** | **1.000** |
| **False alarms per compactor-week (15 %)** | **2.76** | **0.03** |
| **Total (0–100)** | **65.3** | **92.7** |

What the simulator found, and what we fixed in the backend (`backend/app/ai/anomaly.py`, `service.py`):

| Weak spot | Fix |
|---|---|
| Normal sensor noise (±15 kg) raised 671 "unexpected drop" alarms | a drop must be clearly bigger than noise (6σ or 15 %) |
| Normal busy-hour filling looked like spikes | limit = 2.5 × the usual large increase; no spike check after a data gap |
| A few kg below zero on an empty scale = "sensor fault" | allow noise down to about −60 kg |
| **Stuck sensor never noticed** | new `sensor_stuck`: 6 identical readings in a row |
| **Silent device never noticed** | new `data_gap`: no reading for 3 intervals |
| **Slow drift never noticed** (and lifts on a drifted scale were missed) | new `zero_shift`: an empty container must read about 0; emptying also detected from the fill sensor |
| **Duplicate messages stored twice** | the same reading is stored once (`"duplicate": true`) |
| Heavy material that hits the scale's limit looked "normal density" | new `overload`: above the rated payload (also a truck-safety issue) |

**Is it overfitted to our simulator?** We checked on two **new worlds it had never seen** (30 compactors × 90 days each):
**92.7 and 91.0** points; bad data noticed 98.5–99.2 %, false alarms 0.02 per compactor-week. And on the **real Europress
replay** the new rules did not hurt: lifts found 93.0 → 93.4 %.

**Two honest notes.** (1) "Too late" stays around 0.6–0.7 in the simulator because the dataset (and so the model) also
calls a lift "late" when it came long after the order level, not only when the container sat 100 % full; the scorecard
shows both definitions. We did **not** tune the model to our simulator. (2) Adding the order-level setting made the model
better on real data (dataset and replay) but slightly worse on the simulator's early lifts (0.943 → 0.909). We keep it,
because real data is our main evidence.

## 6. Keeping the model right after go-live

Labels do not exist in real life, so we watch two live signals (`GET /api/models/performance`):

1. **Feedback.** The person who checks an alert on site marks it `CORRECT` or `FALSE_ALARM`
   (`POST /api/alerts/{id}/feedback`). This gives the **live precision**. Below 60 % after 20 checks → warning.
2. **Alert rate.** The share of lifts the model flags is compared with the share in testing (stored in
   `model.json`: 11–16 %). More than twice or less than half → warning: a sensor, the customer's routine or the
   season has changed.

When a warning appears: a person reviews it, the confirmed cases become new training data, and the model is
retrained (`python training/train_lift_model.py --feed esp32`, about 1 min) and reloaded without a restart
(`POST /api/models/reload`).

## 7. What this means for Europress

- **With SMART's own data** (press, cycles, order times), the model is accurate enough to act on (F1 ≈ 0.92).
- **With a cheap add-on weighing node only**, it is a useful early warning (F1 ≈ 0.64–0.78), but a person must check.
  Bad data (stuck, silent, drifting, duplicated, overloaded) is caught by rules, not by the model.
- **Biggest gain for little cost:** send the **order type and order time** from SMART's order system with each lift.
  In our test, adding only the order type raised early-lift F1 from 0.84 to 0.90 (organiser-computed inputs).

## 8. Not yet proven

- Only synthetic data. Real sensors, materials and customers will differ: the model must be retrained on real lifts.
- The live test used 40 compactors (small sample); the per-device capacity was estimated from past readings.
- Feedback and drift checks are built and tested, but not yet used by real people.
- The model gives **advice only**: every alert is checked by a person before any action.
