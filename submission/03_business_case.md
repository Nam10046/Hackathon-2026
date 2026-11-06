# Part 3 — Customer value and business case: **SMART Weight Verified**

> All figures come from the **synthetic** Europress dataset (52 fictional customers, 447 devices, 12 months) and from
> **our own hypothetical parameters** (`submission/business_case_params.yaml`), run through the organisers'
> calculator `baselines/business_case.py`. They are not market evidence, not Europress prices and not proven savings.
> Tags: **observed** (record in the data) · **estimated** (our calculation) · **hypothetical** (our assumption).

## 1. The customer problem

The waste operator empties, weighs, grades quality and invoices. The customer pays by those numbers with **no
independent evidence** of what happened. With a weight measured at the compactor, plus the customer's own contract and
invoices, the customer can check the service — and Europress becomes a trusted part of the value chain.

## 2. What the service does

**SMART Weight Verified** — an add-on to SMART, on top of the weighing kit (Part 1):

| Module | Customer benefit | Demo (Part 2) |
|---|---|---|
| **Verified weight** | independent tonnage per lift; €/t per site with mass source shown | cockpit: €/t vs benchmark, device vs weighbridge |
| **Invoice check** | every invoice line recomputed from the contract version in force | findings: duplicate / wrong surcharge / outdated tariff / tonnage mismatch |
| **Service fit** | lifts that were too early (low fill) or too late (overflow) | findings: premature / delayed lifts |
| **Operator scorecard** | neutral facts for contract talks: punctuality, data sharing, billing accuracy | scorecard table |
| **Action center** | proposals (dispute, request data, renegotiate, tender) with evidence; a person approves | `/cockpit` |

## 3. Value found in the data

Annualised, summed over the 52 customers — **estimated** from observed records:

| Value lever | Identified € / year | Our realisation share (hypothetical) | Realisable € / year |
|---|---:|---:|---:|
| Operator performance (missed / late / unshared) | 406,129 | 20 % | 81,226 |
| Contract review (terms vs similar contracts) | 241,692 | 40 % | 96,677 |
| Over-servicing (unnecessary lifts) | 231,625 | 30 % | 69,488 |
| Operator tendering (at renewal) | 145,670 | 30 % | 43,701 |
| Contamination (lost material credit) | 114,002 | 30 % | 34,201 |
| Billing review (invoice ≠ contract) | 44,339 | 60 % | 26,603 |
| **Total — today's levers** | **1,183,457** | | **351,896** |
| + Transport procurement (future model, **hypothesis**: 3 % logistics discount, 30 % realised) | | | 34,550 |
| **Total incl. hypothesis** (used by the calculator for eligibility) | | | **386,445** |

- Customers spend **€5.19 M / year** on these services (observed in invoices) → today's levers ≈ **6.8 % of spend**
  ≈ **€787 per device per year** (average; large fleets much more, small fleets less).
- A 20 % success fee on all realisable value would be ≈ **€77 k / year** across the 52 customers (estimated).
- Realisation shares are deliberately **low**: the dataset's Task C shows that cutting lifts naively is often harmful
  (overflow, emergency fees), and renegotiation depends on notice periods.

## 4. Pricing — derived from customer value, with sensitivity

Rule: a customer buys only if realisable value ≥ **3 ×** the yearly fee (hypothetical buying rule).
Costs (hypothetical): kit amortised over 60 months + cloud + calibration checks = €9 / device / month; onboarding
€600 / customer + €200 / device; support €40 / customer / month.

| Price € / device / month | Eligible customers (value ≥ 3× fee) | Adoption | Devices | Revenue € / yr | Op. cost € / yr | Year-1 contribution € |
|---:|---:|---:|---:|---:|---:|---:|
| 15 | 24 | 25 % | 67 | 31,054 | 10,116 | 3,938 |
| **25** | **17** | **25 %** | **41** | **26,095** | **6,441** | **8,954** |
| 25 | 17 | 40 % | 65 | 41,751 | 10,306 | 14,326 |
| 39 | 9 | 25 % | 18 | 16,262 | 3,051 | 8,211 |

*(Full grid: 3 prices × 3 adoption levels in `business_case_out/business_case_scenarios.csv`.)*

**What the sensitivity tells us**
1. **Higher price → fewer customers qualify.** At €39 only 9 of 52 customers get 3× value; at €15, 24 do.
2. **Value is concentrated in large fleets** (16+ devices: median realisable ≈ €29 k / customer / yr; 2–5 devices: ≈ €1.2 k).
3. **Year 1 is thin because of onboarding**; the model pays back from year 2 (recurring revenue minus operating cost).

**Our recommendation (hypothesis):** list price **€25 / device / month** for fleets ≥ 6 devices, a **lighter €15 tier**
(invoice check + verified weight only) for small fleets, plus an optional **20 % success fee** only on savings that a
human approved *and* the operator confirmed (e.g. a credited invoice line). The fee aligns Europress with the
customer and keeps the entry price low.

## 5. Commercial model for Europress

| Model | Status | Note |
|---|---|---|
| Weighing kit sold with new compactors / as a retrofit | near-term | hardware margin + installation |
| **SMART Weight Verified subscription** (above) | **near-term, our main proposal** | recurring software revenue on the installed base |
| Success fee on confirmed savings | near-term option | only with human approval + operator confirmation |
| Operator tendering as a service | mid-term **hypothesis** | uses the neutral scorecard |
| Tonne-based full service / transport procurement | long-term **hypothesis** | Europress buys transport for the customer; changes its role (today it is not a party) |
| Independent weight data for operators (fewer disputes, better routing) | **hypothesis** | turns the data into a shared, trusted record rather than a weapon |

## 6. Productisation inside SMART

1. **Now:** weighing kit + `Verified weight` data in the existing SMART portal; contract/invoice upload by the customer.
2. **Next:** `Invoice check` + `Action center` with approval and audit trail (as in our demo).
3. **Later:** operator data-sharing API (weighbridge, quality) agreed per contract; the scorecard becomes a shared report.
Everything is **advice with human approval**; nothing is sent to an operator automatically.

## 7. What remains unproven

- Willingness to pay at any price — **no customer interviews** were done.
- That realisation shares (20–60 %) hold in reality; that operators accept disputes, share tickets or that tenders succeed.
- That the weighing kit reaches σ ≤ 1.5 % in the field (Part 1, validation plan).
- That the synthetic world's prices, demand and operator behaviour match reality.
- Future models assume a role Europress does not have today.
