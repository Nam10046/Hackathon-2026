# Project guide — every part explained in simple words

For the whole team. Read this once, and you can explain any part of our project to a judge.

---

## 0. The challenge in one minute

**The story:** Shops and factories press their waste (cardboard, plastic…) into **compactors** made by Europress.
A truck from a **waste company** (the "operator") empties the container, weighs it on **its own scale** (the
"weighbridge") and sends the customer a **bill**.

**The problem:** only the operator knows the weight. The customer has to trust the bill. Nobody can check it.

**Europress asks two things:**
- **Part 1 — Get the weight:** how can the compactor weigh the waste itself, cheaply and accurately?
- **Part 2 — Create value:** if we know the weight, what useful things can we do with it, and how can Europress make money from it?

**How the judges score (100 %):**

| Weight | What they check | Our answer |
|---|---|---|
| 25 % | Weighing idea — does it work, is it accurate, what does it cost | Document 1 |
| 25 % | Value for the customer and the business | Document 3 |
| 20 % | Smart use of data, with calculations you can check | Cockpit + Document 2 & 3 |
| 15 % | Working software + how it connects to Europress SMART | Software + Document 2 |
| 10 % | Can it become a real product | Document 3 |
| 5 % | Clear, honest about limits | All documents |

**What we must hand in:** (1) weighing concept, (2) software demo or video, (3) business case,
plus a list of all tools we used with their licences.

---

## 1. Part 1 — The weighing concept (`submission/01_weighing_concept.md`)

**What it is:** a document that explains *how* a compactor could weigh its own waste. No real machine is needed.

### 1.1 How accurate must it be? (we answered this first)
Instead of guessing, we used Europress's own tool (`weighing_accuracy_value.py`). It pretends to weigh 10,342 real
loads from the dataset with different accuracies and tells us what each accuracy is good for.

**Result:** the scale must be accurate to about **1.5 % of the load** (±45 kg on a 3-tonne load).
- At 1.5 %: 98 % of loads are within ±100 kg (Europress's target) and we catch **95 %** of bills that charge 10 % too much.
- At 5 %: only 47 % of overcharges are caught. Not good enough.

👉 *Why this matters:* the judges see we chose the accuracy **from data**, not from a feeling.

### 1.2 Which sensor? (we compared 5 options)
| Option | Simple explanation | Verdict |
|---|---|---|
| **A. Load sensors under the container** | like a bathroom scale under each corner | ✅ main choice — accurate |
| B. Strain gauges on the frame | measure how much the steel bends | backup — cheaper but drifts with temperature |
| **C. Oil pressure of the press** | the press pushes harder when the container is full | ✅ helper — checks if the scale is lying |
| D. Scale on the truck | the operator's truck weighs it | ❌ data stays with the operator again |
| E. Guess from fill level | software only | ❌ too inaccurate (10–30 %) |

Our choice: **A + C + smart software.**

### 1.3 Where it goes and what it costs
- 4 sensors under the container rails (DUO type) or under the feet (COMBI type). Picture: `submission/img/weighing_concept.png`.
- Data goes through the **SMART controller that is already in the compactor** → no new modem.
- Hardware ≈ **€370–920** per compactor (target under €500), installation ≈ 2–3 hours. *These are estimates.*

### 1.4 Calibration = keeping the scale honest (3 layers)
1. **At installation:** put known weights on it (e.g. a 1,000 kg water tank).
2. **After every emptying:** the container is empty, so the scale must show ~0. If not → warning. *A free check every time.*
3. **Using the truck's ticket** (only if the operator shares it): compare our weight with theirs over the last ~10 loads.
   If they drift apart, we **raise a warning** — we never secretly "fix" our number to match theirs.

### 1.5 Error sources and the test plan
- Things that cause wrong readings: cold/heat, snow on the container, shaking during pressing, waste left *next to* the container. Each has a fix in the document.
- **Test plan:** first a bench test with known weights (1–2 weeks), then 10 real compactors for 8 weeks, with clear pass/fail numbers.

### 1.6 Honest limits
The dataset is simulated, so it **cannot prove** that real hardware works. We say this clearly — the judges reward honesty (5 %).

---

## 2. Part 2 — The software

### 2.1 The big picture
```
 (live)  ESP32 sensor ─MQTT─► Mosquitto ─► Node-RED ─► Backend ─► Database ◄─ Grafana dashboards
 (batch) Europress dataset ─► Analytics job ─────────────────────► Database
                                                Backend ─► Approval page (/cockpit)
```
Two roads, one destination: **live data** from a sensor and **a year of data** from Europress both end in the same database and the same screens.

### 2.2 The Europress dataset (`europress/…/data/competition/public/`)
A **fake but realistic world**: ~500 compactors, 52 customers, 5 waste companies, 1 year. Main tables in simple words:

| Table | What it is |
|---|---|
| `devices`, `sites`, `customers` | the compactors, where they are, who owns them |
| `contracts`, `contract_versions` | the price agreement between customer and operator (can change over time) |
| `telemetry_hourly` | what the compactor measures every hour: fill %, weight |
| `collection_events` | every time a truck came ("a lift") |
| `weighbridge_tickets` | the operator's weight — **only if they share it** |
| `invoices`, `invoice_lines` | the bills the customer received |
| `labels_dev` | the "answers" for learning and self-testing |

### 2.3 The analytics job (`analytics/build_cockpit.py`)
**What it does:** reads the whole dataset, finds problems, and writes the results into our database. Takes ~30 seconds.
Run: `docker compose run --rm analytics`.

It uses Europress's own calculators (called **baselines**) and adds our layer on top:

| Step | Calculator | In simple words | Output table |
|---|---|---|---|
| 1 | B1 | "What *should* each lift cost under the contract?" + cost per tonne | `cp_collections` |
| 2 | B2 | "Which lifts or bill lines look wrong?" (13 kinds of problems) | `cp_flags` |
| 3 | B5 | "How well does each waste company perform?" | `cp_scorecard` |
| 4 | B6 | "What should the customer do?" (dispute, ask for data, renegotiate, change company) | `cp_actions` |
| **Ours** | — | plain-language explanation, evidence, **€ at stake**, evidence tag | all tables |

**Evidence tags** (the judges' rubric asks for this): every number is marked
**OBSERVED** (from a real record), **ESTIMATED** (our calculation or the device), or **HYPOTHETICAL** (an assumed price).

👉 *Honest note:* most problem-finding is still Europress's baseline — **except lift problems**, where we trained our own model (next section).

### 2.3b Our own AI model — the live lift model (`training/train_lift_model.py`)
- **What it learns:** from ~10,700 lifts in the training months, it learns what an **unnecessary early lift** and a
  **too-late lift** look like.
- **What it looks at:** only what the compactor knows *at that moment*: fill %, weight, hours spent full, how fast it
  filled, time since the last lift, the hygiene limit, weekday, material. **No bills, no truck tickets.**
- **How good:** tested on 2 months it never saw, with Europress's own scorer: F1 **0.93** (unnecessary) and **0.92**
  (late). Europress's simple rules get 0.72 / 0.77; their ML gets about the same as ours, **but it needs the truck's
  weight and the bill**, which come days later.
- **Why that matters:** ours can warn **live**, the moment the container is emptied → it is the "real-time" brain for SMART.
- **How it runs live:** exported as ONNX files in `models/lift_premature/` and `models/lift_delayed/`. When the backend
  sees an emptying, it builds the same features from the readings and asks the model. Tested with a fake early lift
  and a fake late lift — both gave the right alert.

### 2.4 The Grafana cockpit (http://localhost:3000/d/value-cockpit)
| Panel | What it shows | Which requirement |
|---|---|---|
| 4 big numbers | 18,297 lifts · −€5 M net (customers pay much more than they earn back) · €971 k at stake · 202 actions waiting | customer value |
| Findings by type | which problems cost the most € | data-driven value |
| Findings per month | problems over time | data-driven value |
| Recommended actions | proposals + status (pending / approved / rejected) | human approval |
| Cost per tonne by site | €/t vs benchmark, red = expensive; shows if the weight was **measured** or **estimated** | €/t optimisation (named in the brief) |
| Operator scorecard | punctuality, missed visits, data sharing, billing accuracy — **neutral** | operator transparency |
| Device vs weighbridge | lifts where our scale and theirs differ > 10 % | the reason weighing matters |
| Findings with evidence | every problem with its source record | traceability |

### 2.5 The approval page (http://localhost:8000/cockpit)
**What it does:** the system only **suggests**. A real person decides.
- **Show evidence** → the exact records behind the suggestion (bill line, lift, amount).
- Enter your name + a note → **Approve** or **Reject**.
- **Revert** → change your mind. Nothing is ever deleted; the full history is kept (`action_decisions` table).

👉 *Why:* Europress's rules say "advice only, a human approves". The judges' rubric gives top marks for
"explicit proposal + reason + way to undo". This page is exactly that.

### 2.6 Traceable economics (`submission/02_software_demo.md` §5)
We follow one real example from the data, step by step:
lift `OP-B-003200015` → no truck ticket shared → contract version V2 says €1,041.39 per lift → the bill has **two
lines** for this lift → finding "duplicate line", €1,041.39 at stake → a person approves the dispute.
👉 This is the "row-level audit trail" the rubric wants.

### 2.7 The live road = SMART integration (15 %)
How a real Europress compactor would plug in:
1. **ESP32 sensor** (`firmware/`) — our stand-in for the SMART controller. Reads the scale, sends JSON.
2. **Mosquitto (MQTT)** — the post office for sensor messages.
3. **Node-RED** (`nodered/`) — the delivery driver; also has **test buttons** so we can demo without hardware.
4. **Backend checks every reading** (`backend/app/ai/`):
   - `anomaly.py` — broken sensor, sudden jump, weight drop, wrong material (by density), emptied, nearly full
   - `forecast.py` — "full in about X hours"
   - `value.py` — weight × price = € value
   - `ml.py` — drop a trained AI model in `models/` and it is used automatically
5. Results go to the same database → Grafana.

### 2.8 Online version (Rahti + TigerData)
- **TigerData** = the shared database in the cloud, so the whole team sees the same data.
- **Rahti** = CSC's cloud that runs the backend + Grafana with a public link for judges. Guide: `deploy/rahti/README.md`.
- Rahti only allows web traffic, so there the sensor sends by **HTTPS with a secret key** instead of MQTT.

---

## 3. Part 3 — The business case (`submission/03_business_case.md`)

### 3.1 The product: "SMART Weight Verified"
An add-on to Europress SMART with 5 modules: **verified weight · invoice check · service fit (too early / too late
lifts) · operator scorecard · action center**. Each module = something you can see in our demo.

### 3.2 How much value is in the data?
Europress's own calculator added up 6 kinds of value over the 52 customers:
- **Found:** €1.18 M per year.
- **Realistic share we think customers really get:** 20–60 % per kind → **€352 k per year**
  = 6.8 % of what customers spend (€5.19 M) ≈ **€787 per compactor per year**.
- We chose **low** shares on purpose (the data shows that cutting lifts carelessly often costs *more*).

### 3.3 Price — calculated, not guessed
Rule we assumed: *a customer buys only if they get at least 3× the price back.*
Then we tested 3 prices × 3 adoption levels:
- €39/month → only 9 customers qualify · €25 → 17 · €15 → 24.
- Lesson: **the value is mostly in big fleets** (16+ compactors).

**Recommendation:** €25 per compactor per month for bigger customers, a cheaper €15 version for small ones, plus an
optional **20 % success fee** only on savings a person approved *and* the operator confirmed.

### 3.4 How Europress makes money + how it becomes a product
- Now: sell the weighing kit + the subscription. Later (clearly marked as ideas): tendering service, buying transport for customers.
- Step-by-step into SMART: weight data first → invoice check + approvals → data sharing with operators.

### 3.5 What is not proven
No customer interviews, the prices are our assumptions, the data is simulated. We say it openly.

---

## 4. Licences and assumptions (`submission/04_licences_and_assumptions.md`)
The brief requires a list of **every tool, library, dataset and service** with its licence and any commercial limits.
Important ones to know:
- **Grafana = AGPL-3.0:** fine to use; if Europress *changes* Grafana and sells it as a service, they must share their changes.
- **Rahti:** meant for research/education; commercial use needs an agreement.
- **The dataset:** synthetic, hackathon rules, not uploaded to GitHub.

---

## 5. How to run everything (cheat sheet)
```powershell
docker compose up -d --build            # start the server
docker compose run --rm analytics       # load the Europress year into the cockpit
```
| Open | What |
|---|---|
| http://localhost:3000/d/value-cockpit | Cockpit |
| http://localhost:8000/cockpit | Approval page |
| http://localhost:1880 | Node-RED + test buttons |
| http://localhost:8000/docs | API |
| http://localhost:8080 | Adminer (look inside the database) |

---

## 6. Words you will hear
| Word | Meaning |
|---|---|
| Lift / collection | the truck empties the container |
| Weighbridge / ticket | the operator's big scale / its weight record |
| Tare | weight of the empty truck; an old tare makes every weight wrong |
| €/t | euros per tonne — the key cost number |
| Material credit | money back for valuable waste (cardboard, plastic) |
| Baseline | Europress's simple reference solution we should beat |
| Validation | the part of the data we may test ourselves on |
| Evidence tag | OBSERVED / ESTIMATED / HYPOTHETICAL label on a number |
| Human approval | the system suggests, a person decides |
