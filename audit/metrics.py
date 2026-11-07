"""Small, tested KPI helpers shared by the dashboard."""
from __future__ import annotations

import numpy as np
import pandas as pd


def cost_per_tonne_known(lifts: pd.DataFrame) -> tuple[float, int, float]:
    """Collection EUR/t over lifts with a known, positive mass only (cost and tonnes from the SAME lifts).
    Returns (eur_per_t or NaN, number of lifts with unknown mass, their collection cost)."""
    known = lifts.mass_kg.notna() & (lifts.mass_kg > 0)
    t = lifts.loc[known, "mass_kg"].sum() / 1000
    cpt = float(lifts.loc[known, "collection_cost_eur"].sum() / t) if t > 0 else float("nan")
    return cpt, int((~known).sum()), float(lifts.loc[~known, "collection_cost_eur"].sum())
