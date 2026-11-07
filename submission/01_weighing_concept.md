# Part 1 — Weigh at Source: a weighing concept for Europress compactors

**Team:** Hackathon-2026 · Since AI Hackathon 2026 · Europress Group challenge
**Status:** concept + calculations + simulation. No prototype and no test on a real machine (as the brief allows).
All prices are **estimates from public list prices**, not quotes. Every number in §4, §6 and §7 is recomputed by
`python submission/weighing_calc.py` from the assumptions written in that file.

![Weighing concept](img/weighing_concept.png)

## Summary

| | Our choice |
|---|---|
| Primary sensor | **4 × 10 t C3 shear-beam load cells** in mounting kits with lift-off, horizontal and **overload stops at 110 %** |
| DUO | cells under the **docking frame** where the container stands (they stay on site with the compactor) |
| COMBI | the unit is lifted whole, so the cells sit in a **ground weigh frame (4 weigh pads)** that stays on site |
| Electronics | 4-channel 24-bit weight transmitter → **RS-485 Modbus into the SMART controller** (existing modem) |
| When we weigh | **only at idle**: ram retracted, door closed, no lift, 30 s stable |
| Zero and tare | sensor **zero only when the frame is empty**; container tare from an **RFID-keyed tare register**, updated only on an identified, verified-empty return — **no blind auto re-tare** |
| Accuracy on net material (3 t load) | σ ≈ **1.1 % typical** (99.8 % within ±100 kg) · **2.2 % pessimistic (87.5 % — below the 95 % target)** |
| Cost per device | **factory-fit €1,360–3,350** (≈ €22–43 / month) · **retrofit €3,070–7,160 installed** (≈ €40–83 / month) |

## 1. What accuracy do we actually need?

We ran the organisers' tool `examples/weighing_accuracy_value.py` on the competition dataset. The reference was 10,342 shared
single-load weighbridge tickets. **This is a sensitivity simulation, not a hardware test.**

| Concept accuracy (1σ, % of load) | 2.5–3.5 t loads within ±100 kg | Median €/t error | Detects +10 % invoice tonnage | False alarm on correct invoices |
|---:|---:|---:|---:|---:|
| 1.0 % | 99.8 % | 0.85 % | 94.7 % | 0.8 % |
| **1.5 %** | **98.3 %** | **1.1 %** | **95.0 %** | **1.0 %** |
| 2.0 % | 90.4 % | 1.4 % | 94.8 % | 1.6 % |
| 3.5 % | 65.9 % | 2.4 % | 75.6 % | 1.9 % |
| 5.0 % | 50.5 % | 3.4 % | 46.7 % | 1.8 % |

**Design target: σ ≤ 1.5 % of the load (≈ 45 kg at 3 t).** The challenge asks for ±100 kg at 95 %, which needs
σ ≤ 51 kg. Even at 2 % the weight still detects +10 % invoice tonnage 95 % of the time, so a weaker sensor still
gives value.

## 2. Sensing options compared

| Option | Measures | Expected accuracy* | Cost | Retrofit | Verdict |
|---|---|---|---|---|---|
| **A. Load cells (shear beams) under the container's supports** | the weight force itself, at 4 points | 0.5–2 % of load | €1.4–7 k installed | needs a frame or support change, 1 day | ✅ **primary** — the only option that measures mass directly and independently |
| B. Strain gauges bonded on the existing frame | steel deformation | 2–5 % | low | easy, invisible | ❌ temperature drift and creep, every unit needs its own calibration; fallback only |
| C. Hydraulic pressure / motor current of the press | compaction resistance | not a mass (depends on material, oil temperature) | ≈ €0–90, often present | trivial | ➕ **plausibility check** (density, "mass rose but the press did not run") |
| D. Truck hooklift scale | mass during the lift | 1–2 % | on the operator's truck | not Europress-owned | ❌ the data stays with the operator, which is exactly the problem |
| E. Camera (+ fill × density model) | what is visible, fill level, contamination | 10–30 % for mass | €150–400 | easy | ➕ for **contamination and fill**, not for weight |

\*Expected ranges from typical industrial practice; proven only by the validation plan (§11).

**Why A:** the customer needs **independent evidence of tonnes**. Only a load-cell scale measures mass without
depending on material, temperature or the operator. C and E stay as cheap cross-checks that help catch faults.

## 3. Placement

| | DUO (compactor stays, container is taken) | COMBI (whole unit is taken) |
|---|---|---|
| Where | 4 cells under the **docking frame / rails**; the container stands on the frame when docked | **ground weigh frame** with 4 weigh pads under the unit's skids; the frame stays on site |
| What is weighed | container + material (the press is not on the frame) | press + container + material (press is part of the tare) |
| Gross range | 4.5 t empty … ≈ 14.5 t full (design) | ≈ 4.4–5.6 t empty … ≈ 14–15 t permitted gross (similar units) |
| Horizontal forces | the press pushes material into the container and the hook drags it: these forces go into **horizontal stops and the docking lock**, never into the cells | the hook drags the unit across the pads: same horizontal stops |
| Connection | transmitter box next to the SMART controller, RS-485 | transmitter on the ground frame; data via the site connector the unit plugs into (or short-range radio to the unit's SMART controller) |

## 4. Load check — are 10 t cells big enough, and what protects them?

Assumptions (in `weighing_calc.py`): empty container 4.5 t, material up to 10 t (dataset DUO 95th percentile 9.7 t),
a 20 t hooklift as the heaviest possible case, 65 % of the load on the heavier end and 55 % on the heavier side.

| Case | Force on worst cell | % of rated | What carries it |
|---|---:|---:|---|
| Static, full container (design) (normal weighing) | 5.2 t | 52% | cell |
| Static, truck-limit container (20 t) (overfilled worst case) | 7.2 t | 72% | cell |
| Hooklift pick-up, full container (rear end carries all, x1.25 dynamic) (each pick-up) | 10.0 t | 100% | cell |
| Hooklift pick-up, 20 t container (rare) | 13.8 t | 138% | cell up to 11 t, rest into the overload stop |
| Set-down impact, empty container (x2.0) (each return) | 5.0 t | 50% | cell |
| Set-down impact, full container (x1.5) (rare) | 12.0 t | 120% | cell up to 11 t, rest into the overload stop |
| Horizontal drag when pulled (friction 0.3 x 14.5 t) | 4.3 t sideways | — | horizontal stops / docking guides, never the cells |

Cell never sees more than 11 t (110 %) — below its safe overload of 15 t (150 %).
Normal static use: 52% of rated → good resolution, long fatigue life.

**Design rules that follow**
- **4 × 10 t** cells: normal weighing uses about **half** of their range (good resolution, low fatigue).
- **Overload stops at 110 %** (≈ 1 mm gap) take the rare peaks: a set-down of a full container, or an overfilled 20 t one.
  A cell never sees more than 11 t; its safe overload is 15 t.
- **Every pick-up loads the rear cells to about their rated capacity**, which is why the validation plan includes 1,000
  pick-up cycles (§11, step 3).
- **Side forces never go through the cells**: mounting kits with horizontal stops and lift-off protection, plus the
  existing docking guides and press coupling.

## 5. Container identity and tare: no blind re-tare

DUO containers are **swapped** between sites, can come back with **residue**, and differ by hundreds of kilograms.
So "set to zero when a container arrives" would hide exactly the errors we want to find.

| Moment | What the system does |
|---|---|
| **Frame empty** (no RFID tag, weight near zero, stable 60 s) | **sensor zero** — the only time zero is updated. If the zero moved by more than 2 % of capacity → flag "frame zero shift" (ice, debris, damaged cell) and do not re-zero |
| **Container docks** | read its **RFID tag** → look up its tare in the **tare register** (value, date, how it was verified) |
| **Verified-empty return** = known ID + a completed emptying in SMART + fill sensor < 5 % | if the weight is within ±30 kg of the registered tare → update the tare and mark it *verified* |
| Return weighs **more** than tare + 30 kg | **residue** flag; the tare is **not** updated; both lifts are marked for review |
| Return weighs **less** than tare − 30 kg | "container changed or wrong tag" flag; tare marked *unverified* until checked |
| **Unknown or missing tag** | tare = median for that container type, status **MODEL_ESTIMATE** (±150 kg); never shown as measured |
| New container | first docking empty and confirmed clean → initial tare, status *verified-initial* |

Every lift's net weight carries a status: **MEASURED** (verified tare, sensor OK) · **MODEL_ESTIMATE** (estimated tare) ·
**UNVERIFIABLE** (sensor fault, no stable reading, zero invalid) → shown as "no weight", never as 0 kg.
COMBI works the same way, with the tag on the unit (the unit is the "container").

## 6. Error budget on the NET material mass

Net = gross − container tare − zero, so the tare register's error counts in full.

| Source | Typical | Pessimistic |
|---|---:|---:|
| Load cells (C3, combined error 0.02 % FS, 4 cells) | 4 | 6 |
| Zero drift with temperature since last empty-frame zero (0.015 % FS/10 °C, 4 cells) | 6 | 22 |
| Span drift with temperature (0.011 %/10 °C of gross) | 1 | 2 |
| Mechanics: friction in mounts, not level, rail contact (% of gross) | 26 | 45 |
| Container tare from the RFID register | 15 | 35 |
| Frame zero (debris, ice, water on the frame) | 5 | 15 |
| Reading noise / wind / settling (idle-only, 30 s average) | 5 | 15 |
| **Total σ (root-sum-square)** | **32 kg = 1.1%** | **65 kg = 2.2%** |
| **Share of 3 t loads within ±100 kg** | **99.8%** | **87.5%** |

Target ±100 kg at 95 % needs σ ≤ 51 kg. Typical meets it; pessimistic does NOT.
Pessimistic with mechanics ≤ 0.45 % of gross and tare ≤ 25 kg: σ = 53 kg → 94.3% within ±100 kg
Pessimistic with mechanics ≤ 0.4 % of gross and tare ≤ 20 kg: σ = 48 kg → 96.3% within ±100 kg

**Honest conclusion:** in **normal conditions** we meet the target easily. In a **pessimistic** case (cold, a tare
register that is not well maintained, and mount friction) **we miss it: about 87.5 % of loads within ±100 kg instead
of 95 %.** The two levers are mechanics (≤ 0.4–0.45 % of gross) and the tare register (≤ 20–25 kg). Both are pass
criteria in the field pilot (§11). Even the pessimistic σ ≈ 2.2 % still detects a +10 % invoice tonnage about 95 % of
the time (§1).

Biases kept **out** of the budget, and how we handle them:
- **Snow and rain** on the container: real mass, but not material (wet snow on a 14 m² roof ≈ 100–150 kg). The weighbridge
  weighs it too. We flag lifts after snowfall (weather + mass rising without the press running).
- **Stale stored truck tares** at the weighbridge: in the dataset, several trucks' **stored** tare differs from the same
  truck's **weighed** tare by **360–440 kg** (median over 20–210 tickets each; e.g. `OP-C-V14`: 15,320 vs 15,760 kg).
  A stored tare that is too low adds that amount to every net weight on the ticket. So we compare only against
  **single-load, WEIGHED-tare** tickets.

## 7. Bill of materials and cost

#### Retrofit on an installed DUO

**Retrofit on an installed DUO: €3,070–7,160** → €40–83 per device per month (over 8 years + €100/year service)

| Item | Low € | High € |
|---|---:|---:|
| 4 × 10 t C3 shear-beam cells (alloy IP67 €185 … stainless IP68 €440 each) | 740 | 1,760 |
| 4 × mounting kits with lift-off, horizontal and overload stops | 480 | 1,200 |
| 4-channel 24-bit weight transmitter, RS-485 Modbus (≈ $350 list) + IP66 box | 300 | 450 |
| Adapting the docking frame/rails onto the 4 weigh modules (steel, galvanised) | 300 | 900 |
| UHF RFID reader IP67 at the dock + on-metal tags on containers | 300 | 800 |
| Cables, surge protection, inclinometer (optional) | 150 | 350 |
| Installation on site: 2 technicians × 1 day | 600 | 1,200 |
| Calibration with reference load + weighbridge check | 200 | 500 |

#### Factory-fit in a new unit

**Factory-fit in a new unit: €1,360–3,350** → €22–43 per device per month (over 8 years + €100/year service)

| Item | Low € | High € |
|---|---:|---:|
| 4 × 10 t C3 cells at volume price | 600 | 1,200 |
| Mounting kits designed into the frame | 200 | 600 |
| 4-channel ADC board in the SMART controller (or the same transmitter) | 60 | 300 |
| Frame changes in production | 200 | 500 |
| UHF RFID reader + tags | 200 | 500 |
| Cables | 50 | 100 |
| Factory calibration | 50 | 150 |

**What this means for the business case:** the hardware costs more than our first estimate (€370–920 covered only
sensor parts). On new units Europress can offer **factory-fit as an option on the compactor price**. Retrofit is a
**project sale** for large fleets, where the value per device is highest. Part 3 uses these hardware costs.

## 7b. Edge electronics — working prototype on an ESP32-C6

The weighing rules above are not only on paper: they run on a real **ESP32-C6 edge node** (`firmware/edge_node`).
The load cells are simulated on the board (we have no 10 t cells), but **everything after the load cell is real code on real
hardware**, feeding the live product pages in Grafana.

| Rule in this concept | What the board does |
|---|---|
| weigh only at idle, 30 s stable (§ Summary) | samples 10×/s, reports a weight only when the press is still and 3 s of samples are within 4σ (demo-shortened window) |
| one bad sample must not move the result (§10) | median-of-5 spike filter on the board; removed spikes are counted and reported |
| frozen sensor (§10) | 5 s of identical raw samples → quality `STUCK` |
| emptying = new cycle, no blind re-tare (§5) | emptying detected on the board (≥ 10 % → < 5 % of capacity) and sent at once |
| data must survive network loss | offline ring buffer (240 readings), sent later with their original time |
| weights must be evidence for invoice checks | every reading **HMAC-SHA256 signed**; firmware protected by **Secure Boot V2 + flash encryption** |

In production the same firmware would read the 4-channel weight transmitter over RS-485 Modbus instead of the simulated cells.

## 8. Installation (retrofit DUO, 2 technicians, ≈ 1 day)

1. **Survey:** foundation level and strength, docking rails, cable route, photos.
2. **Lift the docking frame/rails** (jacks or crane). Place 4 base plates on the levelled foundation and anchor them.
3. **Fit the 4 mounting kits and cells.** Set the overload-stop gaps (110 %) and the horizontal stops. Fit earth straps across each cell (welding and lightning currents).
4. **Lower the frame** onto the modules. Check that every cell takes load (corner readings within ±15 % of each other).
5. **Cable** to the transmitter box at the SMART controller (RS-485, surge protection).
6. **Fit the RFID reader** at the dock and tags on every container in rotation. Weigh each one empty → initial tare.
7. **Calibrate** (§9) and do one test lift with the operator.

## 9. Calibration

1. **Zero:** empty frame, stable.
2. **Low-load point:** a known ≈ 1 t reference (certified test weights or a weighed water IBC) at the centre.
3. **High-load span:** a container loaded to 8–10 t gross whose mass is known from a certified weighbridge with a
   **weighed** tare on the same day (or test weights). Low + high points give the span and show non-linearity.
4. **Corner test:** the 1 t reference on each corner → per-channel digital equalisation in the transmitter.
5. **In use:** zero at every empty-frame moment; tare check at every verified-empty return. A rolling comparison with
   single-load, weighed-tare tickets **only flags for service** if it drifts by more than 2σ. It **never re-scales
   automatically**, so a wrong weighbridge cannot "calibrate away" a real difference.

## 10. Error sources and mitigation

| Error source | Effect | Mitigation |
|---|---|---|
| Temperature (−25…+40 °C; cells compensated −10…+40 °C) | zero and span drift | zero at every empty-frame moment; temperature logged; cold-test pass criterion |
| Mount friction, frame not level, rail contact | biggest error term (§6) | self-aligning mounting kits, levelled base plates, corner test, inclinometer option |
| Container tare (swaps, residue, repairs) | wrong net | RFID tare register, verified-empty updates only, residue flag |
| Impact at set-down and pick-up | overload, zero shift | 110 % stops, lift-off protection, zero-shift alarm |
| Side forces (press, hook drag) | bias, damage | horizontal stops; cells carry vertical load only |
| Vibration while compacting | noise | weigh only at idle, 30 s average |
| Snow, ice, water | + mass | flag; same mass is on the weighbridge |
| Cell or cable failure | wrong or missing mass | per-cell diagnostics in the transmitter, status UNVERIFIABLE, never a fake number |
| Weighbridge reference (20 kg resolution, stale stored tares) | false differences | compare only single-load, weighed-tare tickets; compare distributions, not single tickets |

## 11. Validation plan (7 steps, with pass criteria)

| # | Step | Pass criteria |
|---|---|---|
| 1 | **Component check:** cell certificates (OIML R60 C3), transmitter, IP rating | documents complete; cells within C3 limits |
| 2 | **Full-range linearity** on one installed frame: 0 → 12 t in 1 t steps, up and down, centre and 4 corners | error ≤ ±30 kg at every step; corner error ≤ 0.2 %; up/down difference ≤ 20 kg |
| 3 | **Proof load and impact:** 30 min static at 125 % of design load per cell; 1,000 pick-up/set-down cycles with a full container | stops engage as designed; zero shift ≤ 10 kg; span change ≤ 0.1 %; no damage |
| 4 | **Cold and weather:** a winter on site, or −25 → +40 °C | zero drift ≤ 20 kg over the range; no water ingress; ice on the frame flagged |
| 5 | **Tare-swap logic:** 3+ tagged containers rotated; inject 100 kg residue, an untagged container and a swapped tag | 100 % correct flags; register never updated on residue; unknown → MODEL_ESTIMATE |
| 6 | **Field pilot:** 10 units (DUO + COMBI), 8–12 weeks, an operator that shares tickets; reference = single-load **weighed-tare** tickets | **≥ 95 % of 2.5–3.5 t loads within ±100 kg**; bias ≤ 0.5 %; mechanics ≤ 0.45 % of gross; tare register ≤ 25 kg; ≥ 98 % of lifts with a valid weight; ≤ 2 false alarms per device per year |
| 7 | **Value check:** run the cockpit (Part 2) on the pilot data | count findings a person confirms; compare with Part 3's assumptions |

## 12. What this concept does not prove (yet)

- Real accuracy and durability on a real compactor. The dataset is synthetic and **cannot test hardware**.
- That the pessimistic case can be avoided in the field (§6). Today it **misses** the 95 % target.
- Real container tares and load distributions for Europress units (we used values from similar units).
- Prices: public list prices, not quotes. Installation time is an estimate.
- That operators share weighbridge tickets (without them, layers 1–4 of §9 still work).

## Sources for prices and specifications (checked 7 Nov 2026)

- 10 t C3 shear-beam cells: [RS Online – Kern CT 10000-3P2](https://uk.rs-online.com/web/p/strain-gauges/0858010),
  [Brecknell shear beam price list](https://www.centralcarolinascale.com/PDF/BRECKNELL/Brecknell-Shear-Beam-Load-Cells.pdf)
  (C3, combined error ≤ 0.02 %, safe overload 150 %),
  [Zemic H8C datasheet](https://totalcomp.com/image/specification_pdf/H8C-Zemic-Datasheet.pdf) (zero drift ≤ 0.015 % FS / 10 °C, span ≤ 0.011 % / 10 °C, compensated −10…+40 °C)
- Mounting kit with lift-off protection and horizontal stop: [WIKA FA205 data sheet](https://www.wika.com/media/Data-sheets/Force/Accessories/ds_ac5017_en_co.pdf)
- 4-channel RS-485 weight transmitter: [Laumas TLB4 (list price)](https://weightechusa.com/laumas-digital-weight-transmitter-tlb4-multi-channel)
- UHF RFID: [Impinj R700 reader](https://rfid.it/en/295-categories), [on-metal container tags](https://rfidsolution.com/?p=6538)
- Similar compactor containers: [Compoman 20 m³ (4,435 kg empty, 14 t gross)](https://www.werktuigen.com/compoman-k1812%2F20+%2F+press+container+%2F+20m3/wt-186-26886),
  [Avermann MPC 20 (5,580 kg empty, 15 t permitted)](https://www.machineseeker.com/avermann-mpc+20pal%2Fhkv/i-22821045),
  [20 t hooklift](https://ronco.com.au/?p=3228)
