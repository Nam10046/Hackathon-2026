# Part 2 — Software demo: Customer Value Cockpit + SMART integration pathway

**Repo:** https://github.com/Nam10046/Hackathon-2026 · **Data:** Europress SMART Material Value Engine v1.0.1
(synthetic, competition profile: 447 public devices, 52 customers, 1 Oct 2025 – 15 Oct 2026).
**All numbers below are synthetic-world results. None is a real saving or a real price.**

## 1. What the demo shows (in one sentence)

The device's own data (weight, fill, status) plus the customer's own papers (contract, invoices) give the customer an
**independent, explainable view** of the waste service they buy — and every proposed action waits for a **human decision**.

## 2. Architecture

```
            ┌─────────────── LIVE PATH (SMART integration) ───────────────┐
 Compactor  │ weigh bars + ram pressure + fill  →  SMART controller        │
 (Part 1)   │      MQTT (local / on-prem)   or   HTTPS + API key (cloud)   │
            └───────────────────────────┬──────────────────────────────────┘
                                        ▼
 Customer papers  ─────────►  Backend (FastAPI) ── rules + ONNX models ── PostgreSQL (TigerData)
 (contracts, invoices)         │  /api/readings  /api/cockpit/…                │
 Operator data (if shared) ──► │                                               ▼
 (weighbridge, quality)        └── /cockpit approval page          Grafana "Customer Value Cockpit"
            ┌──────────── BATCH PATH (this demo, Europress dataset) ────────────┐
            │ audit/ (Task B/B2/C2, as-of) + B1 → build_cockpit.py        │
            │ + evidence text + € at stake + evidence tags → cp_* tables         │
            └───────────────────────────────────────────────────────────────────┘
```

Both paths end in the **same tables and the same cockpit**, so the live device feed is the production version of
what the demo shows with the dataset.

## 3. Run it (≈ 5 minutes)

```powershell
git clone https://github.com/Nam10046/Hackathon-2026.git ; cd Hackathon-2026
# unzip the Europress participants package into .\europress\  (git-ignored)
docker compose up -d --build
docker compose run --rm analytics          # first time ≈ 5 min: team audit pipeline (Task B/B2/C2) + cockpit tables
```
| Open | What |
|---|---|
| http://localhost:3000/d/value-cockpit | Grafana — Customer Value Cockpit (6 linked pages: Overview, Findings, Cost & weight, Operators, Actions, Live sensors) |
| http://localhost:8000/cockpit | Approve / reject / revert proposed actions |
| http://localhost:8000/docs | API (OpenAPI) |
| http://localhost:1880 | Node-RED: live sensor path + test buttons |

Online (team + judges): CSC Rahti + TigerData, see `deploy/rahti/README.md`.

## 4. Demo walkthrough (recorded video script, ~4 min)

1. **1 Overview** — customers paid **€6.1 M** for waste service and got **€1.2 M** back for recyclables (18,297 lifts,
   synthetic). The system found **1,896 issues** (the same problem on the same compactor counted once; 12,313 single
   records) worth **€1.14 M to check**, and **202 decisions wait for a person**.
2. **2 Problems found** — biggest pools: lifts emptied too early (€499 k, found by **our AI model**), cost per tonne far
   above normal (€347 k), old price on the invoice (€120 k), dirty loads losing their credit (€98 k). Example issue:
   *Mall Customer 0055, Jyväskylä site 4 — emptied too early 130 times, €39.9 k* → open the records below it.
3. **Cost per tonne by site** — colour-coded % of benchmark; every row shows the share of lifts with **observed** mass
   (weighbridge/invoice) vs **estimated** (device). Rows without any mass source show no €/t (we never invent it).
4. **Device vs weighbridge** — lifts where the two disagree by > 10 %. Shown neutrally: the cause can be the device,
   the truck tare, combined loads or side waste.
5. **Operator scorecard** — punctuality, missed visits, ticket sharing, weight bias, billing accuracy per operator ×
   region — from the customer's own records.
6. **Approval page** — open a *dispute invoice* proposal → **Show evidence** → the source rows → enter name + note →
   **Approve**. The Grafana table turns it green. **Revert** puts it back to pending; history is kept.
7. **Live path** — click a Node-RED test button (or the ESP32): a reading arrives, the backend checks it, an alert shows.

## 5. Traceable economics — one example, row by row

Proposal: **dispute invoice** for customer device `CMP-00320` (€1,041.39 flagged).

| Step | Record | Value | Tag |
|---|---|---|---|
| Lift | `collection_events` COL-00320-0015, job **OP-B-003200015**, 16 Feb 2026 | COMPLETED, device est. 9,555 kg | observed / estimated |
| Weighbridge | `weighbridge_tickets` for OP-B-003200015 | **not shared** | — |
| Contract | `contract_versions` CTR-00320-**V2** (ANNUAL_INDEXATION, from 1 Jan 2026) | FIXED_PER_LIFT, lift fee **€1,041.39** | hypothetical tariff |
| Invoice | `invoice_lines` INV-00320-202602 **L003** and **L004** | LIFT_FEE 1 × €1,041.39 — **twice** for the same job | observed |
| Expected | B1 contract calculation: 1 lift fee + transport | 1 × €1,041.39 | estimated |
| Finding | DUPLICATE_LINE, € at stake €1,041.39 | "The same charge appears twice on the invoice" | estimated |
| Decision | human approves / rejects in `/cockpit` → `action_decisions` | who, when, note | observed |

The cockpit's **Source record** column and the approval page's **Show evidence** expose this trail for every finding.

## 6. Analytical core and honest scores

Two parts, both reproducible:
- **Team audit pipeline** (`audit/`, built by our teammate): Task B problems, Task B2 waste-company scorecard and Task C2
  proposals. Everything is recomputed from **as-of snapshots**: only data published before the decision or report date.
- **Our live lift model** (`models/lift_*`) for early and late lifts. It uses only what the compactor knows at that
  moment, so the same model runs live in the backend.
- Lift costs (Task A) come from the organisers' contract calculator B1.

We re-ran the audit pipeline from scratch on both datasets (7 Nov 2026): every score below came out identical to the
team's reported numbers. Official evaluator, public labels:

| Task | Organisers' baseline | **Ours** | Notes |
|---|---:|---:|---|
| A — € per lift, exact to the cent (validation) | 96.4 % (B1) | 96.4 % | we use B1 |
| **B — problems, macro-F1 (validation)** competition | 0.782 (hybrid ML + rules) | **0.8205** | audit picks ML or rules per problem type (on train months only) + our lift model for early/late lifts (audit alone 0.8201) |
| B — quickstart | 0.753 (hybrid) · 0.856 (rules) | **0.856** | equal to the rule baseline here: the per-type choice picked rules |
| **B2 — scorecard 0–100** competition | 67.75 (B5) | **96.28** | final report = month end + 45 days, Helsinki calendar days (DST-safe); preliminary (+15 d): 94.36 |
| B2 — quickstart | 78.3 | **94.28** | |
| **C2 — mean regret per case** competition (207 cases) | €240.07, 77.4 % captured (B6) | **€11.82, 98.9 % captured** | decided only with data known on the decision date |
| C2 — quickstart (7 cases) | €0 (B6) | €17.73, 0 % captured | one renegotiation missed: the July invoice was not issued yet on the decision date. **B6 gets 0 by using later data.** Too few cases to conclude |

**No future data (leakage test).** For every decision date we cut the data the way the dataset's own as-of rules do
(tickets published, invoices issued, lifts done, contract versions in force), then recompute everything. The test
corrupts all data published after the cut-off; the decision must not change. On the competition data the earlier
full-sample method changed **72 of 639** evidence rows (5 decisions); the snapshot method changes **0 of 639**.
Honest cost: C2 regret rose from €2.31 (leaky) to €11.82, and dispute precision is 0.59, because whether an invoice was
already disputed is not known on the decision date.

**Label use.** Task B: train-period labels only (to fit the ML and to choose ML vs rules per type, on a 2/3–1/3 time split
of train). B2 and C2: fixed rules, nothing fitted on labels. Validation/dev labels: scoring only.

**Bugs found and fixed along the way** (team audit): future data in tare/B1/flags; "any invoice that day" cleared
forgotten-invoice flags (now one-to-one typo match, ambiguous → NEEDS_REVIEW); weight bias shown as 0 % without evidence
(now MEASURED / MODEL_ESTIMATE / UNVERIFIABLE + coverage); €/t mixing in unknown-mass costs; report date off by one day,
then a DST shift; approvals keyed by row index (now dataset + case + action); in-process snapshot cache; typo'd job
references not resolved in the euro calculation (49/116 weight-basis lines counted in full).
Merging into our cockpit we also fixed: invoice-line findings had no site or waste company (now via invoice → contract).

**Our live lift model** (`training/train_lift_model.py`, `models/lift_*`): train months only, scored on validation:

| Problem type | Rules B2 | ML B4 | Audit choice | **Our live model** |
|---|---:|---:|---:|---:|
| Emptied too early (F1) | 0.716 | 0.925 | 0.925 | **0.927** |
| — justified lifts wrongly flagged | 0 | 13 | 13 | **8** |
| Emptied too late (F1) | 0.773 | 0.919 | 0.919 | **0.922** |

B4 needs the weighbridge weight and the invoice, which arrive days later. Our model gets the same accuracy from
**only what the compactor knows at the lift**, so it runs live (accuracy on live data: Part 6).

**Every number carries a tag** (observed / estimated / hypothetical), every finding a plain-language calculation and a
likely cause (operator, device, logistics, billing, data entry or normal noise; checked on **train** labels: 82 % right
cause, 85 % right side), and every proposal an expected value with a low–high range, e.g.
*EV = acceptance chance 0.5 × annual gap to peer-median terms €465 − effort €150 = €82.59 (range −€10 … €176)*.
**Proposal values overlap: they are not savings to add up.**

## 7. SMART integration pathway

| Step | What | Where in the repo |
|---|---|---|
| 1 | Weighing kit on the device; SMART controller sends `{device, weight_kg, fill_pct, ts}` | `firmware/compactor_node/` (ESP32 reference), `CONTRACT.md` |
| 2 | Transport: MQTT on-prem, or HTTPS + API key to the cloud (Rahti only allows HTTP/S) | `nodered/`, `deploy/rahti/` |
| 3 | Ingest + checks per reading (sensor fault, spike, unexpected drop, contamination by density, nearly full) | `backend/app/ai/anomaly.py` |
| 4 | Customer uploads contract + invoices; operator shares tickets via API when agreed | `analytics/build_cockpit.py` (batch today) |
| 5 | Findings + proposed actions → human approval → audit trail | `backend/app/cockpit.py`, `/cockpit` |
| 6 | Models improve without code changes: drop an ONNX model in `models/` | `backend/app/ai/ml.py`, `training/` |

## 8. Ground rules we follow

Synthetic data only · advice only, a human approves (with reversal) · neutral towards operators (discrepancies, not
accusations) · no €/t without a mass source · no tuning on the test period.
