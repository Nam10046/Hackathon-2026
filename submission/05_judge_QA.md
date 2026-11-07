# Questions the judges may ask — and our honest answers

Short answers in simple words. Every number comes from our own runs on the **synthetic** Europress dataset.
Golden rule: **say what is proven and what is not.** Judges reward honesty (5 % "clarity, uncertainty, limits").

**One-sentence pitch:** *A cheap scale at the compactor plus the customer's own contract and invoices give an
independent, explainable view of the waste service — and every proposed action waits for a person.*

---

## A. The weighing concept (Part 1 — 25 %)

**1. Why sensors under the container, and not the truck's scale?**
The truck's scale belongs to the waste company — that is exactly the data the customer cannot check today. Our sensors
belong to the customer's compactor, so the weight is **independent**.

**2. How accurate is it? How do you know?**
We did not guess. We used Europress's own tool on 10,342 real-looking loads: we need **σ ≤ 1.5 % of the load**
(about ±45 kg on 3 t). Then 98 % of loads are within ±100 kg and we catch 95 % of invoices that charge 10 % too much. Our error budget gives
**σ ≈ 1.1 % in normal conditions, but 2.2 % in a pessimistic case — then only 87.5 % of loads are within ±100 kg, below
the 95 % target.** We say so openly; the pilot must show the mechanics and the tare register are good enough (Part 1 §6, §11).

**3. What does it cost? Can old compactors get it?**
**Factory-fit ≈ €1,360–3,350**, **retrofit ≈ €3,070–7,160 installed** (1 day, 2 technicians) — from public list prices,
not quotes. That is ≈ €22–43 (factory) or €40–83 (retrofit) per device per month over 8 years. It uses 4 × 10 t
industrial load cells with overload stops, because a hooklift pick-up loads each rear cell to about 10 t.

**3b. DUO containers are swapped — how do you know the empty weight?**
Every container has an **RFID tag**; its empty weight is in a **tare register**. We only update it when a known container
comes back **verified empty** (emptying done, fill < 5 %, weight within ±30 kg). Heavier → "residue" flag, no update.
Unknown container → the weight is marked **estimate**, never "measured". The scale is zeroed only when the frame is empty.

**4. What about snow, rain, ice or frozen waste?**
We weigh only at rest. When the frame is empty the scale must read about zero; if not, we raise a warning (ice, debris,
damaged cell) instead of re-zeroing. A returned container heavier than its registered empty weight → "residue" flag. The press's oil pressure and the fill level are a second opinion: if the weight goes up but they don't, it is
probably snow on the lid, not waste.

**5. What if the waste company never shares its weighbridge tickets?**
Calibration layers 1 and 2 (known weights at installation, auto-zero after every lift) still work. Tickets only make
it better. And we **never secretly adjust** our weight to match theirs — a growing gap becomes a warning.

**6. Why not just use the hydraulic pressure, which is free?**
Pressure measures how hard the press pushes (density, resistance), not weight. It is a good **cross-check**, not a scale.

**7. DUO and COMBI are different — does it work for both?**
DUO: sensors under the container rails, they stay on site. COMBI: sensors in the feet, or a ground frame that stays on
site. Same electronics and software.

---

## B. Data and analytics (20 %)

**8. Why does the data show so many problems?**
It is a **test world** built on purpose with 38 types of problems so teams have something to find — it is not
calibrated to real life (Europress's documentation says so). Also, one wrong setting repeats on every lift, so we group:
**12,313 single records → 1,896 issues** (same problem on the same compactor counted once).

**9. Is your analysis better than Europress's baselines?**
Yes, on every scored task, with **their** evaluator (we re-ran everything and got identical numbers):

| | Their baseline | **Ours** |
|---|---:|---:|
| Finding problems (Task B, F1) | 0.782 | **0.82** |
| Waste-company scorecard (B2, 0–100) | 67.75 | **96.28** |
| Contract actions (C2, money lost per case) | €240 | **€12** (98.9 % of the possible value) |

For early/late lifts our live model is as good as their ML, but it needs only what the compactor knows at that moment,
so it can warn **live**, before the invoice. On the small quickstart dataset we beat the hybrid baseline but only
**equal** the simple rules (0.856), and C2 has only 7 cases there, so we do not claim it works equally everywhere.

**10. How many of your alarms are wrong?**
Early/late lifts: about **6 % and 10 %** of alarms are wrong (precision 0.94 / 0.90). "Dispute this invoice" proposals:
**41 %** are not confirmed (precision 0.59), because on the decision date you cannot yet see whether an invoice was
already disputed. That is why nothing happens automatically: a person checks the evidence first.

**11. Did you cheat by using the answers or the future?**
No, and we test it. **Answers:** only train-month labels are used, to fit the ML and to choose ML or rules per problem type.
Validation labels are only for scoring. **Future:** every decision and every monthly report is computed from a snapshot
of the data known on that date. A test deliberately corrupts everything published later, and the outputs do not change:
**0 of 639** evidence rows change (an earlier version changed 72). Being honest cost us: the regret rose from €2.31 to €11.82.

**11b. Why is a difference not an accusation?**
Every finding gets a likely cause: **operator** (e.g. a stale stored truck tare), **device** (sensor), **logistics** (side
waste, shared truck), **billing**, **data entry** (typo'd job reference) or **normal noise**. Checked on train labels it picks
the right side 85 % of the time. Example: **238 of 313** "never invoiced" alarms (76 %) were really invoice lines with a typo in the job reference.

**12. How do you compute € per tonne when the weight is missing?**
Weight source order: truck ticket → invoice tonnes → our device → **none**. If there is no weight, we show **no €/t**
— we never invent it. The cockpit shows how much of the weight was measured vs estimated.

**13. How do we know your euros are right?**
The contract calculator reproduces **96.4 % of amounts exactly to the cent** on validation. And every finding links to
its source record — e.g. job `OP-B-003200015`: contract V2 says €1,041.39 per lift, the invoice has it twice.

**13a. Does it still work on live data from a simple sensor?**
Yes, but less accurately, and we measured exactly how much. With only weight + fill (an ESP32), F1 is **0.78 / 0.64**
(too early / too late), compared with **0.93 / 0.92** on full SMART data. So we run a second model trained on exactly the
ESP32 inputs. Then we played **67,000 real readings from 40 compactors** into our backend one by one: it found
**93 % of the lifts by itself** and gave F1 0.65 / 0.74 (small sample). Details: `06_model_accuracy_and_live_data.md`.

**13b. How do you know the model stays right after go-live?**
Two live checks (`/api/models/performance`): (1) people mark alerts **correct / false alarm** → live precision;
(2) the share of lifts flagged is compared with testing (11–16 %) — far off means the data changed (sensor, routine,
season) → review and retrain (1 minute, reload without restart).

**13c. What did the live test teach you?**
Three real problems we fixed: the simple sensor knows less (→ second model), the backend computed inputs slightly
differently from the training data (→ we now train on the same live code), and sensor noise looked like emptyings
(→ false emptyings from 112 to 35).

**13c-2. How do you know it handles bad sensor data?**
We built a **simulator with known answers** that injects spikes, impossible values, a stuck sensor, missing hours, slow
drift, glitches, duplicate messages and overloads. The first run scored **65 / 100**: it caught only half of the bad
data and gave 2.8 false alarms per compactor per week. We fixed the rules; now **92.7 / 100**, **100 % of the bad data
noticed** and 0.03 false alarms per week, and the same on two new simulated worlds (92.7, 91.0). We never train the AI
on simulator data. `simulator/README.md`.

**13d. What should Europress send to make it better?**
The **order type and order time** with each lift. SMART already has them, and adding just the order type raised
early-lift F1 from 0.84 to 0.90 in our test.

---

## C. Customer and business value (25 % + 10 %)

**C0. Does the weighing hardware pay for itself?**
Not everywhere, and we show where. Median value is ≈ **€40 per device per month**; hardware is €22–43 (factory-fit) or
€40–83 (retrofit) per month. So: factory-fit pays back in **2.5–6 years for 16+ device fleets**, not for small fleets.
Our plan: start everyone on the **invoice/contract check without hardware**, offer weighing as a **factory option**
for large fleets, and retrofit only the devices with the highest value (the cockpit ranks them). Part 3 §4b.

**14. Why would a customer pay?**
In the test world, realistic savings are about **€787 per compactor per year** (6.8 % of what customers spend).
At €25/month (€300/year) a customer gets ~2.6× back on average — but value is concentrated in **big fleets**, so we
propose €25 for fleets ≥ 6 devices, a lighter €15 tier, and an optional 20 % success fee only on confirmed savings.

**15. Isn't this just a weapon against the waste companies?**
No. We call differences **discrepancies, not accusations**, and show that causes can also be our sensor, combined
truck loads or missing data. A shared, trusted weight can mean **fewer disputes for operators too**.

**16. Europress is not part of the customer–operator contract. Why should Europress do this?**
Europress's own stated strategy (dataset README): become a more integral part of the waste value chain and give
customers tools to steer and verify the services they buy. Independent weight is the key that unlocks that.

**17. What is proven, and what is not?**
Proven (in the synthetic world): the calculations, the findings, the model's accuracy, the working software.
**Not proven:** real hardware accuracy, real prices and savings, willingness to pay (no customer interviews), and that
operators will share data or accept disputes.

**18. How does this become a product?**
1) weighing kit + verified weight in SMART → 2) invoice check + approval workflow (our demo) → 3) data-sharing with
operators. Later ideas (clearly labelled hypotheses): tendering as a service, tonne-based full service.

---

## D. Software and SMART integration (15 %)

**19. Does it really run live, or only on the dataset?**
Both. Live: sensor → MQTT (or HTTPS on the cloud) → backend checks every reading → when a container is emptied,
the **live lift model** judges it → alert. Tested end-to-end with an early and a late lift. Batch: the full dataset
year builds the cockpit in about a minute.

**20. Does it ever act on its own?**
Never. Every proposal has evidence, a named person approves or rejects with a note, it can be reverted, and every
decision is kept (audit trail).

**21. Is the data secure and trustworthy?**
Sending data needs an API key, the cloud uses HTTPS, the database is not public. **Not done yet:** signing every
reading on the device (tamper-proof chain) — a natural next step.

**22. Personal data / GDPR?**
None. All data is synthetic; customers and operators are fictional. In a real service, contracts and invoices stay the
customer's data and are only used with their permission.

**23. Licences — anything risky?**
Mostly MIT / BSD / Apache. Watch-outs: **Grafana is AGPL-3.0** (fine unmodified; changes offered as a service must be
shared), CSC Rahti is for research/education. Full list: `04_licences_and_assumptions.md`.

---

## If you don't know the answer
Say: *"We haven't tested that yet — here is how we would test it."* Then point to the validation plan (Part 1 §6) or
"what remains unproven" (Part 3 §7).
