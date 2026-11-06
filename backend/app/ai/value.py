"""Material value. Owner: AI / business person.

Value = weight × price per kg. Positive = customer earns, negative = customer pays.
Idea for later: reduce the price when contamination is detected (quality penalty).
"""


def material_value(weight_kg: float, material: dict) -> dict:
    w = max(weight_kg, 0)
    return {
        "value_eur": round(w * material["price_eur_per_kg"], 2),
        "co2_saved_kg": round(w * material["co2_factor"], 1),
    }
