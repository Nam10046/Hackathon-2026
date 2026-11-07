"""Weighing concept numbers: load check, error budget, cost. Every input is an ASSUMPTION written here.
Run:  python submission/weighing_calc.py      (prints the tables used in 01_weighing_concept.md)
This is arithmetic on stated assumptions, NOT a hardware test.
"""
from math import erf, sqrt

# ---------------- 1. LOAD CHECK (DUO, 4 shear-beam cells under the docking frame) ----------------
CELL_T = 10.0            # rated capacity per cell (t)
STOP_T = 11.0            # mechanical overload stop engages at 110 % of rated
SAFE_T = 15.0            # cell safe overload 150 % (datasheet value for C3 shear beams)
TARE_T = 4.5             # closed compactor container, empty (similar units: 4.4-5.6 t)
PAYLOAD_T = 10.0         # design max material (dataset DUO p95 9.7 t; similar unit payload 9.6 t)
TRUCK_LIMIT_T = 20.0     # 20 t hooklift: heaviest container a truck could lift
END_SHARE = 0.65         # share on the heavier end (material packed towards one end)
SIDE_SHARE = 0.55        # share on the heavier side (uneven ground / load)

G = TARE_T + PAYLOAD_T
cases = [
    ("Static, full container (design)", G * END_SHARE * SIDE_SHARE, "normal weighing"),
    ("Static, truck-limit container (20 t)", TRUCK_LIMIT_T * END_SHARE * SIDE_SHARE, "overfilled worst case"),
    ("Hooklift pick-up, full container (rear end carries all, x1.25 dynamic)", G * 1.0 * SIDE_SHARE * 1.25, "each pick-up"),
    ("Hooklift pick-up, 20 t container", TRUCK_LIMIT_T * 1.0 * SIDE_SHARE * 1.25, "rare"),
    ("Set-down impact, empty container (x2.0)", TARE_T * 1.0 * SIDE_SHARE * 2.0, "each return"),
    ("Set-down impact, full container (x1.5)", G * 1.0 * SIDE_SHARE * 1.5, "rare"),
]
print("## Load check per cell (4 x 10 t cells, stop at 110 %)\n")
print("| Case | Force on worst cell | % of rated | What carries it |")
print("|---|---:|---:|---|")
for name, f, when in cases:
    carried = "cell" if f <= STOP_T else f"cell up to {STOP_T:.0f} t, rest into the overload stop"
    print(f"| {name} ({when}) | {f:.1f} t | {f / CELL_T:.0%} | {carried} |")
print(f"| Horizontal drag when pulled (friction 0.3 x {G:.1f} t) | {0.3 * G:.1f} t sideways | — | horizontal stops / docking guides, never the cells |")
print(f"\nCell never sees more than {STOP_T:.0f} t (110 %) — below its safe overload of {SAFE_T:.0f} t (150 %).")
print(f"Normal static use: {G * END_SHARE * SIDE_SHARE / CELL_T:.0%} of rated → good resolution, long fatigue life.\n")

# ---------------- 2. ERROR BUDGET on NET material mass (3 t load) ----------------
LOAD_KG = 3000
GROSS_KG = LOAD_KG + TARE_T * 1000
CELL_KG = CELL_T * 1000


def budget(p):
    terms = {
        "Load cells (C3, combined error 0.02 % FS, 4 cells)": sqrt(4) * 0.0002 * CELL_KG * p["cell_x"],
        "Zero drift with temperature since last empty-frame zero (0.015 % FS/10 °C, 4 cells)":
            4 * 0.00015 * CELL_KG * p["dT"] / 10 * p["cold_x"],
        "Span drift with temperature (0.011 %/10 °C of gross)": 0.00011 * GROSS_KG * p["dT"] / 10,
        "Mechanics: friction in mounts, not level, rail contact (% of gross)": p["mech_pct"] / 100 * GROSS_KG,
        "Container tare from the RFID register": p["tare_kg"],
        "Frame zero (debris, ice, water on the frame)": p["zero_kg"],
        "Reading noise / wind / settling (idle-only, 30 s average)": p["dyn_kg"],
    }
    return terms, sqrt(sum(v * v for v in terms.values()))


TYPICAL = dict(cell_x=1.0, dT=10, cold_x=1.0, mech_pct=0.35, tare_kg=15, zero_kg=5, dyn_kg=5)
PESSIMISTIC = dict(cell_x=1.5, dT=25, cold_x=1.5, mech_pct=0.60, tare_kg=35, zero_kg=15, dyn_kg=15)
t_terms, t_sig = budget(TYPICAL)
p_terms, p_sig = budget(PESSIMISTIC)


def within(sig, lim=100):
    return erf(lim / (sig * sqrt(2)))


print(f"## Error budget on net material mass — {LOAD_KG / 1000:.0f} t load, {GROSS_KG / 1000:.1f} t gross (1σ, kg)\n")
print("| Source | Typical | Pessimistic |")
print("|---|---:|---:|")
for k in t_terms:
    print(f"| {k} | {t_terms[k]:.0f} | {p_terms[k]:.0f} |")
print(f"| **Total σ (root-sum-square)** | **{t_sig:.0f} kg = {t_sig / LOAD_KG:.1%}** | **{p_sig:.0f} kg = {p_sig / LOAD_KG:.1%}** |")
print(f"| **Share of 3 t loads within ±100 kg** | **{within(t_sig):.1%}** | **{within(p_sig):.1%}** |")
need = 100 / 1.96
print(f"\nTarget ±100 kg at 95 % needs σ ≤ {need:.0f} kg. Typical meets it; pessimistic does NOT.")
# what must hold for the pessimistic case to pass
for mech, tare in [(0.45, 25), (0.40, 20)]:
    _, s = budget({**PESSIMISTIC, "mech_pct": mech, "tare_kg": tare})
    print(f"Pessimistic with mechanics ≤ {mech} % of gross and tare ≤ {tare} kg: σ = {s:.0f} kg → {within(s):.1%} within ±100 kg")

# ---------------- 3. COST per device (list prices = estimates) ----------------
RETROFIT = {  # item: (low €, high €)
    "4 × 10 t C3 shear-beam cells (alloy IP67 €185 … stainless IP68 €440 each)": (740, 1760),
    "4 × mounting kits with lift-off, horizontal and overload stops": (480, 1200),
    "4-channel 24-bit weight transmitter, RS-485 Modbus (≈ $350 list) + IP66 box": (300, 450),
    "Adapting the docking frame/rails onto the 4 weigh modules (steel, galvanised)": (300, 900),
    "UHF RFID reader IP67 at the dock + on-metal tags on containers": (300, 800),
    "Cables, surge protection, inclinometer (optional)": (150, 350),
    "Installation on site: 2 technicians × 1 day": (600, 1200),
    "Calibration with reference load + weighbridge check": (200, 500),
}
FACTORY = {
    "4 × 10 t C3 cells at volume price": (600, 1200),
    "Mounting kits designed into the frame": (200, 600),
    "4-channel ADC board in the SMART controller (or the same transmitter)": (60, 300),
    "Frame changes in production": (200, 500),
    "UHF RFID reader + tags": (200, 500),
    "Cables": (50, 100),
    "Factory calibration": (50, 150),
}
YEARS, SERVICE = 8, 100   # amortisation years; yearly check/recalibration €/device
print("\n## Cost per device (estimates from list prices, not quotes)\n")
for title, items in [("Retrofit on an installed DUO", RETROFIT), ("Factory-fit in a new unit", FACTORY)]:
    lo, hi = sum(v[0] for v in items.values()), sum(v[1] for v in items.values())
    print(f"**{title}: €{lo:,}–{hi:,}** → €{lo / (YEARS * 12) + SERVICE / 12:.0f}–{hi / (YEARS * 12) + SERVICE / 12:.0f} per device per month "
          f"(over {YEARS} years + €{SERVICE}/year service)\n")
    print("| Item | Low € | High € |\n|---|---:|---:|")
    for k, (a, b) in items.items():
        print(f"| {k} | {a:,} | {b:,} |")
    print()
