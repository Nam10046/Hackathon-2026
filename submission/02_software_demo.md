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
            │ analytics/build_cockpit.py → organisers' calculators B1/B2/B5/B6   │
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
docker compose run --rm analytics          # ≈ 1 min: builds the cockpit from the dataset
```
| Open | What |
|---|---|
| http://localhost:3000/d/value-cockpit | Grafana — Customer Value Cockpit |
| http://localhost:8000/cockpit | Approve / reject / revert proposed actions |
| http://localhost:8000/docs | API (OpenAPI) |
| http://localhost:1880 | Node-RED: live sensor path + test buttons |

Online (team + judges): CSC Rahti + TigerData, see `deploy/rahti/README.md`.

## 4. Demo walkthrough (recorded video script, ~4 min)

1. **Cockpit header** — 18,297 completed lifts; net material contribution −€4.97 M (customers pay more for service than
   they get back in credits); **€971 k at stake** across 11,612 findings; **202 actions waiting for a human**.
2. **Findings by type** — biggest € pools: cost per tonne > 2× benchmark (€347 k), low-fill lifts without a reason
   (€331 k), invoice prices differing from the contract version in force (€120 k), contamination credit loss (€98 k).
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

We **reuse the organisers' transparent calculators** as the core (they are rule-based, explainable and auditable) and add
the evidence layer, € impact, evidence tags and the human-approval workflow. Scores on the **public validation period**
(`python baselines/run_all.py competition`):

| Task | Method | Validation result |
|---|---|---|
| A — € reconstruction | B1 contract calculator | 96.4 % of net amounts exact to the cent; €/t within 5 % on 97.6 % |
| B — irregularities | B2 rules (macro-F1) | 0.73 (hybrid ML + rules 0.78) |
| B2 — operator scorecard | B5 from customer records | 67.8 / 100 |
| C2 — operator/contract actions | B6 rules | value captured 77 %, mean regret €240 per case (vs €1,064 doing nothing) |

**Why rules first:** every proposal can be explained in one sentence and checked against a row. The ML option
(`models/` folder, ONNX) is plugged in as a *second opinion* (`ml_anomaly`), never as the only reason for an action.

**Known gaps we would close next** (organisers' failure list): precautionary customer orders before weekends and
false-high fill sensors on on-call devices (missed by B2), drift vs outdated-tare separation, overflow risk when reducing
frequency, and using weighbridge instead of invoice tonnage for repricing.

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
